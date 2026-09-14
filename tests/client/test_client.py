"""The recording client refuses to be used without provenance."""

import pytest

from agentic_base.client import PendingRun, RunRecorder, git_revision
from agentic_base.domain.outcomes import DataClass, IsolationTier, LabelSource
from agentic_base.domain.run_record import RunStatus


def test_a_recorder_without_a_code_revision_is_refused_at_construction() -> None:
    """Refusing here is better than refusing at the first record, which is often in production."""
    with pytest.raises(ValueError, match="code_revision is required"):
        RunRecorder("http://localhost", tenant="hpml", code_revision="")


def test_a_recorder_without_a_tenant_is_refused() -> None:
    with pytest.raises(ValueError, match="tenant is required"):
        RunRecorder("http://localhost", tenant="", code_revision="abc")


def test_git_revision_returns_empty_outside_a_checkout_instead_of_raising(
    tmp_path,
) -> None:
    """The caller decides. The service then refuses the empty value, which is the intent."""
    assert git_revision(str(tmp_path)) == ""


def test_a_failing_run_is_still_recorded_and_marked_failed(monkeypatch) -> None:
    """A run that crashed is a measurement. Losing it biases whatever it was part of."""
    recorded: list[PendingRun] = []
    recorder = RunRecorder("http://localhost", tenant="hpml", code_revision="abc")

    def _capture(pending: PendingRun) -> str:
        recorded.append(pending)
        return "run-1"

    monkeypatch.setattr(recorder, "record", _capture)

    with pytest.raises(RuntimeError), recorder.run(item="task-1") as run:
        run.model = "some-model"
        raise RuntimeError("agent blew up")

    assert len(recorded) == 1
    assert recorded[0].status is RunStatus.FAILED
    assert recorded[0].failure_kind == "RuntimeError"


def test_a_successful_run_records_its_duration(monkeypatch) -> None:
    recorded: list[PendingRun] = []
    recorder = RunRecorder("http://localhost", tenant="hpml", code_revision="abc")

    def _capture(pending: PendingRun) -> str:
        recorded.append(pending)
        return "run-2"

    monkeypatch.setattr(recorder, "record", _capture)

    with recorder.run(item="task-2") as run:
        run.num_steps = 3

    assert recorded[0].elapsed_ms >= 0
    assert recorded[0].status is RunStatus.COMPLETED


def test_the_recorder_can_supply_every_field_a_writer_owns() -> None:
    """A field the record gains and the client cannot send is a field no client writes."""
    from dataclasses import fields

    from agentic_base.domain.outcomes import RunRecordCreate

    set_by_recorder = {"tenant", "code_revision"}
    set_by_label = {"resolved", "label_source", "degraded", "instrument"}
    pending = {f.name for f in fields(PendingRun)}

    assert set(RunRecordCreate.model_fields) - set_by_recorder - set_by_label <= pending


def test_what_the_recorder_sends_is_what_the_service_stores(
    test_client, monkeypatch
) -> None:
    import agentic_base.client as client_module

    # The real client, with the network replaced by the application. TestClient refuses a
    # timeout, which the real transport needs, so that one argument is dropped.
    monkeypatch.setattr(
        client_module.httpx,
        "post",
        lambda url, json, headers, timeout: test_client.post(
            url, json=json, headers=headers
        ),
    )
    recorder = RunRecorder("http://testserver", tenant="svc", code_revision="abc1234")

    with recorder.run(
        item="mr-101",
        arm="reviewer-2026.09",
        principal="urn:example:alice",
        classification=DataClass.INTERNAL,
        isolation_tier=IsolationTier.VIRTUALISED,
        disclosure="each reply begins 'Automated review'",
    ) as run:
        run.messages = [{"role": "user", "content": "review this"}]
    recorder.approve(
        run.run_id,
        action="push fix",
        decision="approved",
        by="urn:example:bob",
        at="2026-09-14",
    )
    recorder.label(run.run_id, resolved=True, label_source=LabelSource.USER_FEEDBACK)

    stored = test_client.get(f"/runs/{run.run_id}").json()
    assert stored["principal"] == "urn:example:alice"
    assert stored["classification"] == "internal"
    assert stored["isolation_tier"] == "virtualised"
    assert stored["disclosure"] == "each reply begins 'Automated review'"
    assert stored["approvals"][0]["by"] == "urn:example:bob"
    assert stored["label_source"] == "user_feedback"


def test_the_recorder_sends_its_token_and_is_refused_without_one(
    app, test_client, monkeypatch
) -> None:
    import agentic_base.client as client_module
    from agentic_base.auth import AccessPolicy, get_access_policy

    monkeypatch.setattr(
        client_module.httpx,
        "post",
        lambda url, json, headers, timeout: test_client.post(
            url, json=json, headers=headers
        ),
    )
    token = "token-for-svc-00000001"
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
        enabled=True, tokens={token: frozenset({"svc"})}
    )
    try:
        with_token = RunRecorder(
            "http://testserver", tenant="svc", code_revision="a", token=token
        )
        without = RunRecorder("http://testserver", tenant="svc", code_revision="a")
        with with_token.run(item="ok") as run:
            pass
        # The test client's responses come from its own httpx build, so match by name and status.
        with (
            pytest.raises(Exception, match="401") as refused,
            without.run(item="refused"),
        ):
            pass
        assert type(refused.value).__name__ == "HTTPStatusError"
    finally:
        app.dependency_overrides.pop(get_access_policy)

    assert run.run_id
