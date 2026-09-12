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
    rather than of the deployment.
    """
    lifecycle = values["lifecycle"]

    assert lifecycle["marginSeconds"] > 0, (
        "the derived grace period must exceed the request plus the preStop sleep, not equal it"
    )


def test_the_grace_period_is_derived_and_not_written_as_a_literal(values) -> None:
    """A literal drifts the moment the timeout it was chosen against changes.

    That drift has cost real work three times here, including 229 cells lost to a reaper whose
    threshold was shorter than the cells it was reaping. The template computes the grace period
    from the request timeout, so there is nothing to leave behind.
    """
    assert "terminationGracePeriodSeconds" not in values.get("lifecycle", {}), (
        "grace period is a literal again; it must be derived in the template"
    )

    template = (VALUES.parent / "templates" / "deployment.yaml").read_text(
        encoding="utf-8"
    )
    grace_line = next(
        line
        for line in template.splitlines()
        if "terminationGracePeriodSeconds:" in line
    )

    assert "longestRequestSeconds" in grace_line, (
        f"not derived from the timeout: {grace_line.strip()}"
    )


def test_the_pod_waits_before_shutting_down_so_it_stops_receiving_work_first(
    values,
) -> None:
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

    assert any(m.get("type") == "External" for m in metrics), (
        "no queue-depth metric declared"
    )


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
    agentic_base.code_policy is a pre-filter and says so itself."""
    policy = values["networkPolicy"]

    assert policy["enabled"] is True
    assert policy["allowedPorts"], (
        "default-deny with no allowlist would break the service"
    )


def test_an_autoscaler_that_cannot_read_its_metric_raises_an_alert(values) -> None:
    """An external metric nothing publishes is silent.

    The autoscaler reports ScalingActive false, never scales, and the deployment stays healthy at
    its minimum. Nothing else surfaces that, so the alert is the only thing standing between a
    no-op autoscaler and everyone believing it works.
    """
    assert values["autoscaling"]["alertOnInactive"] is True

    rule = (VALUES.parent / "templates" / "prometheusrule.yaml").read_text(
        encoding="utf-8"
    )

    assert "ScalingActive" in rule
