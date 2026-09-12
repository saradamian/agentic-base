"""The recording client refuses to be used without provenance."""

import pytest

from app.client import PendingRun, RunRecorder, git_revision
from app.domain.run_record import RunStatus


def test_a_recorder_without_a_code_revision_is_refused_at_construction() -> None:
    """Refusing here is better than refusing at the first record, which is often in production."""
    with pytest.raises(ValueError, match="code_revision is required"):
        RunRecorder("http://localhost", tenant="hpml", code_revision="")


def test_a_recorder_without_a_tenant_is_refused() -> None:
    with pytest.raises(ValueError, match="tenant is required"):
        RunRecorder("http://localhost", tenant="", code_revision="abc")


def test_git_revision_returns_empty_outside_a_checkout_instead_of_raising(tmp_path) -> None:
    """The caller decides. The service then refuses the empty value, which is the intent."""
    assert git_revision(str(tmp_path)) == ""


def test_a_failing_run_is_still_recorded_and_marked_failed(monkeypatch) -> None:
    """A run that crashed is a measurement. Losing it biases whatever it was part of."""
    recorded: list[PendingRun] = []
    recorder = RunRecorder("http://localhost", tenant="hpml", code_revision="abc")
    monkeypatch.setattr(
        recorder, "record", lambda pending: (recorded.append(pending), "run-1")[1]
    )

    with pytest.raises(RuntimeError), recorder.run(item="task-1") as run:
        run.model = "some-model"
        raise RuntimeError("agent blew up")

    assert len(recorded) == 1
    assert recorded[0].status is RunStatus.FAILED
    assert recorded[0].failure_kind == "RuntimeError"


def test_a_successful_run_records_its_duration(monkeypatch) -> None:
    recorded: list[PendingRun] = []
    recorder = RunRecorder("http://localhost", tenant="hpml", code_revision="abc")
    monkeypatch.setattr(
        recorder, "record", lambda pending: (recorded.append(pending), "run-2")[1]
    )

    with recorder.run(item="task-2") as run:
        run.num_steps = 3

    assert recorded[0].elapsed_ms >= 0
    assert recorded[0].status is RunStatus.COMPLETED
