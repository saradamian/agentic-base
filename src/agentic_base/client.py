"""Recording a run from someone else's agent.

The point of this file is that recording has to be easier than not recording, because whoever is
trying to get one thing working will otherwise wrap the HTTP API themselves, and their wrapper
becomes the real interface.

Two arguments have no default, and that is deliberate. See `RunRecordCreate` for the corpus that
resulted from making provenance optional.

Usage:

    recorder = RunRecorder("https://agentic-base.example.org", tenant="hpml",
                           code_revision=git_sha())

    with recorder.run(item="issue-4312", arm="baseline") as run:
        answer = my_agent(task)
        run.messages = transcript
        run.model = "some-model"

    recorder.label(run.run_id, resolved=True, label_source=LabelSource.OFFICIAL_HARNESS,
                   instrument="harness-1.4")

The context manager records on exit, including when the body raises, because a run that crashed
is a measurement and losing it biases whatever it was part of.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal

import httpx

from agentic_base.domain.outcomes import LabelSource, RunStatus


def git_revision(path: str = ".") -> str:
    """The current commit, or an empty string if this is not a checkout.

    Returns empty rather than raising so a caller can decide. An empty revision will be refused
    by the service, which is the intended outcome: a run that cannot say which code produced it
    cannot be placed against a later change in what a field means.
    """
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


@dataclass
class PendingRun:
    """A run in progress. Fill in what you know; it is recorded when the block exits."""

    item: str = ""
    arm: str = ""
    arm_fingerprint: str = ""
    system_prompt: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    endpoint: str = ""
    precision: str = ""
    status: RunStatus = RunStatus.COMPLETED
    failure_kind: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    joules: float = 0.0
    num_steps: int = 0
    total_tool_calls: int = 0
    extra: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    elapsed_ms: float = 0.0


class RunRecorder:
    """Records runs against a platform instance."""

    def __init__(
        self,
        base_url: str,
        tenant: str,
        code_revision: str,
        *,
        timeout_s: float = 10.0,
    ) -> None:
        if not tenant:
            raise ValueError("tenant is required")
        if not code_revision:
            raise ValueError(
                "code_revision is required. Use git_revision(), or pass the build identifier of "
                "whatever produced this run. A run that cannot name its code cannot be placed "
                "against a later change in what a field means."
            )
        self.base_url = base_url.rstrip("/")
        self.tenant = tenant
        self.code_revision = code_revision
        self._timeout = timeout_s

    def run(self, **kwargs: Any) -> _RunContext:
        """Open a run. Records on exit, including on an exception."""
        return _RunContext(self, PendingRun(**kwargs))

    def record(self, pending: PendingRun) -> str:
        payload = {
            "tenant": self.tenant,
            "code_revision": self.code_revision,
            **{
                key: (value.value if hasattr(value, "value") else value)
                for key, value in vars(pending).items()
                if key not in ("run_id",)
            },
        }
        response = httpx.post(
            f"{self.base_url}/runs", json=payload, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()["run_id"]

    def label(
        self,
        run_id: str,
        *,
        resolved: bool,
        label_source: LabelSource,
        instrument: str = "",
        degraded: bool = False,
    ) -> None:
        """Attach an outcome. The scorer is a required argument and has no default."""
        response = httpx.post(
            f"{self.base_url}/runs/{run_id}/label",
            json={
                "resolved": resolved,
                "label_source": label_source.value,
                "instrument": instrument,
                "degraded": degraded,
            },
            timeout=self._timeout,
        )
        response.raise_for_status()


class _RunContext:
    def __init__(self, recorder: RunRecorder, pending: PendingRun) -> None:
        self._recorder = recorder
        self._pending = pending
        self._started = 0.0

    def __enter__(self) -> PendingRun:
        self._started = time.monotonic()
        return self._pending

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        self._pending.elapsed_ms = (time.monotonic() - self._started) * 1000
        if exc_type is not None and self._pending.status is RunStatus.COMPLETED:
            self._pending.status = RunStatus.FAILED
            self._pending.failure_kind = exc_type.__name__
        self._pending.run_id = self._recorder.record(self._pending)
        return False
