"""Deployment policy that has to hold before anything runs on a cluster.

These assert values rather than rendered manifests, and that is deliberate. The policy used to
live inside template branches, where the only way to check it was to render the chart, which needs
a tool that is not present in every environment. A test that silently skips where the tool is
missing is the failure this project exists to catch, so the policy moved into `values.yaml` and
the templates now render whatever it declares.

Rendering is still worth checking, and it belongs in CI as `helm template` piped through a schema
validator. That check verifies wiring. These verify the policy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

VALUES = Path(__file__).resolve().parents[1] / "charts" / "app" / "values.yaml"


@pytest.fixture(scope="module")
def values() -> dict:
    return yaml.safe_load(VALUES.read_text(encoding="utf-8"))


def test_a_pod_is_given_longer_to_stop_than_its_longest_request_takes(values) -> None:
    """Kubernetes sends SIGTERM, waits, then SIGKILLs.

    A grace period shorter than the longest in-flight request cuts agent runs in half on every
    rolling update, scale-down and node drain, and the loss is recorded as a failure of the run
    rather than of the deployment. The same invariant governed serve drains on the batch
    scheduler: a cleanup whose timer is shorter than the work it must outlive destroys results
    silently.
    """
    lifecycle = values["lifecycle"]

    needed = lifecycle["longestRequestSeconds"] + lifecycle["preStopSleepSeconds"]

    assert lifecycle["terminationGracePeriodSeconds"] > needed, (
        f"grace period {lifecycle['terminationGracePeriodSeconds']}s does not cover a "
        f"{lifecycle['longestRequestSeconds']}s request plus a "
        f"{lifecycle['preStopSleepSeconds']}s preStop"
    )


def test_the_pod_waits_before_shutting_down_so_it_stops_receiving_work_first(values) -> None:
    """Pod deletion and endpoint removal race, so without this the pod refuses traffic that is
    still being routed to it."""
    assert values["lifecycle"]["preStopSleepSeconds"] > 0


def test_autoscaling_never_scales_on_utilisation(values) -> None:
    """On an inference path utilisation is inverted, not merely weak.

    Past a critical concurrency the cache is oversubscribed, the engine evicts in-flight requests
    and recomputes their prefill, and the accelerators stay pinned at full while completing less.
    An autoscaler reading utilisation sees the degraded state as healthy and scales the wrong way.
    """
    metrics = values["autoscaling"]["metrics"]

    utilisation = [
        m
        for m in metrics
        if m.get("type") == "Resource"
        and (m.get("resource") or {}).get("target", {}).get("type") == "Utilization"
    ]

    assert not utilisation, f"utilisation metrics present: {utilisation}"


def test_autoscaling_scales_on_queued_work(values) -> None:
    metrics = values["autoscaling"]["metrics"]

    assert any(m.get("type") == "External" for m in metrics), "no queue-depth metric declared"


def test_the_root_filesystem_is_read_only(values) -> None:
    """Writable paths are declared. An agent that has been talked into writing somewhere finds
    nowhere to write except the one place the chart mounts."""
    assert values["securityContext"]["readOnlyRootFilesystem"] is True


def test_no_api_credential_is_mounted_into_the_pod(values) -> None:
    """The workload never calls the Kubernetes API, and a mounted token is the first thing an
    injected instruction reaches for."""
    assert values["serviceAccount"]["automount"] is False


def test_memory_is_requested_at_its_limit_so_the_pod_cannot_be_evicted(values) -> None:
    resources = values["resources"]

    assert resources["requests"]["memory"] == resources["limits"]["memory"]


def test_ephemeral_storage_is_bounded(values) -> None:
    """The cluster's replacement for the disk guard. An unbounded workload filled a shared disk
    and took a whole campaign down with it."""
    assert "ephemeral-storage" in values["resources"]["limits"]


def test_egress_is_default_deny_with_a_declared_allowlist(values) -> None:
    """This is where generated code meets a real boundary. The structural filter in
    app.code_policy is a pre-filter and says so itself."""
    policy = values["networkPolicy"]

    assert policy["enabled"] is True
    assert policy["allowedPorts"], "default-deny with no allowlist would break the service"
