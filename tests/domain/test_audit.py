"""The audit log the service writes, and what verifying it catches."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from agentic_base.auth import Access
from agentic_base.domain import audit
from agentic_base.domain.audit import AuditEntry, ChainHead
from agentic_base.domain.integrity import (
    GENESIS,
    entry_hash,
    field_digests,
    snapshot,
)
from agentic_base.domain.run_record import (
    Approval,
    LabelSource,
    LabelUpdate,
    RunRecord,
)
from agentic_base.routers import runs


def _post(client, tenant: str = "hpml", item: str = "task-1") -> str:
    body = {
        "tenant": tenant,
        "code_revision": "abc1234",
        "item": item,
        "arm": "baseline",
    }
    response = client.post("/runs", json=body)
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


def _integrity(client, tenant: str = "hpml") -> dict:
    return client.get("/runs/integrity", params={"tenant": tenant}).json()


def test_every_write_through_the_service_leaves_a_log_that_verifies(
    test_client,
) -> None:
    first, second = _post(test_client, item="a"), _post(test_client, item="b")
    test_client.post(
        f"/runs/{first}/label",
        json={"resolved": True, "label_source": LabelSource.OFFICIAL_HARNESS.value},
    )
    test_client.post(
        f"/runs/{second}/approvals",
        json={
            "action": "push",
            "decision": "approved",
            "by": "someone",
            "at": "2026-09-14",
        },
    )

    verdict = _integrity(test_client)

    assert verdict["intact"], verdict["summary"]
    assert verdict["could_have_failed"]
    assert (verdict["entries_checked"], verdict["runs_checked"]) == (4, 2)


def test_each_tenant_has_its_own_chain(test_client) -> None:
    _post(test_client, tenant="one")
    _post(test_client, tenant="two")
    _post(test_client, tenant="one", item="again")

    assert _integrity(test_client, "one")["entries_checked"] == 2
    assert _integrity(test_client, "two")["intact"]


def test_a_record_edited_outside_the_service_is_named(test_client, engine) -> None:
    run_id = _post(test_client)
    with Session(engine) as session:
        record = session.get(RunRecord, run_id)
        assert record is not None
        record.resolved = True
        session.add(record)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["altered_runs"] == [run_id]


def test_a_removed_entry_breaks_the_log(test_client, engine) -> None:
    for item in ("a", "b", "c"):
        _post(test_client, item=item)
    with Session(engine) as session:
        middle = session.exec(select(AuditEntry).where(AuditEntry.seq == 2)).one()
        session.delete(middle)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["first_broken_entry"] == 1


def test_a_run_written_straight_into_the_database_is_reported(
    test_client, engine
) -> None:
    _post(test_client)
    with Session(engine) as session:
        session.add(RunRecord(tenant="hpml", item="smuggled", arm="baseline"))
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert len(verdict["unchained_runs"]) == 1


def test_a_tenant_with_no_runs_is_inconclusive_rather_than_intact(test_client) -> None:
    verdict = _integrity(test_client, "nobody")

    assert not verdict["could_have_failed"]
    assert verdict["summary"].startswith("inconclusive")


def _forged_entry(record: RunRecord, event: str, chain_seq: int = 1) -> AuditEntry:
    """An entry a stale writer would build: chained to GENESIS, whatever came before."""
    values, digests = snapshot(record), field_digests(record)
    return AuditEntry(
        tenant=record.tenant,
        run_id=record.run_id,
        event=event,
        chain_seq=chain_seq,
        audit_fields=values,
        digests=digests,
        previous_hash=GENESIS,
        hash="0" * 64,
    )


def test_two_entries_cannot_chain_to_the_same_predecessor(engine) -> None:
    record = RunRecord(tenant="hpml", item="a", arm="baseline")
    with Session(engine) as session:
        session.add(record)
        audit.append(session, record, "created")
        session.commit()
        session.add(_forged_entry(record, "forged", chain_seq=2))
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_write_that_loses_the_race_is_refused_not_written(
    test_client, monkeypatch
) -> None:
    _post(test_client, item="first")

    def stale(session, record, event, actor=""):
        entry = _forged_entry(record, event)
        session.add(entry)
        return entry

    monkeypatch.setattr(audit, "append", stale)
    response = test_client.post(
        "/runs", json={"tenant": "hpml", "code_revision": "abc", "item": "second"}
    )

    assert response.status_code == 409
    assert response.headers["Retry-After"] == "1"
    monkeypatch.undo()
    assert _integrity(test_client)["runs_checked"] == 1


def test_a_conflict_raised_while_the_entry_is_flushed_is_a_409_not_a_500(
    test_client, monkeypatch
) -> None:
    """PostgreSQL raises the constraint at the flush inside `append`, where SQLite waits for
    the commit; a conflict caught only around the commit was a 500 there."""
    _post(test_client, item="first")

    def stale(session, record, event, actor=""):
        entry = _forged_entry(record, event)
        session.add(entry)
        session.flush()
        return entry

    monkeypatch.setattr(audit, "append", stale)
    response = test_client.post(
        "/runs", json={"tenant": "hpml", "code_revision": "abc", "item": "second"}
    )

    assert response.status_code == 409


def test_a_write_that_loses_the_race_once_is_retried_and_recorded(
    test_client, monkeypatch
) -> None:
    _post(test_client, item="first")
    real_append, calls = audit.append, []

    def stale_once(session, record, event, actor=""):
        calls.append(event)
        if len(calls) == 1:
            entry = _forged_entry(record, event)
            session.add(entry)
            return entry
        return real_append(session, record, event)

    monkeypatch.setattr(audit, "append", stale_once)
    response = test_client.post(
        "/runs", json={"tenant": "hpml", "code_revision": "abc", "item": "second"}
    )
    monkeypatch.undo()

    assert response.status_code == 201
    assert len(calls) == 2
    verdict = _integrity(test_client)
    assert verdict["intact"], verdict["summary"]
    assert verdict["runs_checked"] == 2


# --- two writers to one run: the second must change what the first wrote ----------------------


def _approval(by: str) -> Approval:
    return Approval(action="push", decision="approved", by=by, at="2026-10-29")


_EVERY_TENANT = Access(tenants=None, label_sources=None)


def test_an_approval_from_a_writer_holding_an_older_copy_keeps_the_one_before_it(
    test_client, engine
) -> None:
    """The lost update: the second writer read the run before the first committed, and wrote
    its own copy back. The log, chained to the entry it could see, verified intact."""
    run_id = _post(test_client)
    with Session(engine) as late, Session(engine) as early:
        # Held, as a request holds what it read: the identity map keeps only weak references.
        older_copy = late.get(RunRecord, run_id)
        assert older_copy is not None
        runs.record_approval(run_id, _approval("carol"), early, _EVERY_TENANT, None)
        runs.record_approval(run_id, _approval("dave"), late, _EVERY_TENANT, None)

    stored = test_client.get(f"/runs/{run_id}").json()
    assert [approval["by"] for approval in stored["approvals"]] == ["carol", "dave"]
    assert _integrity(test_client)["intact"]


def test_an_approval_after_a_label_it_did_not_see_leaves_the_run_unaltered(
    test_client, engine
) -> None:
    """With an older copy the entry snapshot missed the label the row had, and the run read as
    altered for good."""
    run_id = _post(test_client)
    label = LabelUpdate(resolved=True, label_source=LabelSource.OFFICIAL_HARNESS)
    with Session(engine) as late, Session(engine) as early:
        # Held, as a request holds what it read: the identity map keeps only weak references.
        older_copy = late.get(RunRecord, run_id)
        assert older_copy is not None
        runs.label_run(run_id, label, early, _EVERY_TENANT)
        runs.record_approval(run_id, _approval("carol"), late, _EVERY_TENANT, None)

    stored = test_client.get(f"/runs/{run_id}").json()
    assert stored["resolved"] is True
    assert len(stored["approvals"]) == 1
    verdict = _integrity(test_client)
    assert verdict["intact"], verdict["summary"]
    assert verdict["altered_runs"] == []


def test_simultaneous_approvals_are_all_kept_and_the_log_verifies(test_client) -> None:
    run_id = _post(test_client)
    writers = 8
    start = threading.Barrier(writers)

    def approve(index: int) -> int:
        start.wait()
        return test_client.post(
            f"/runs/{run_id}/approvals",
            json={
                "action": f"step-{index}",
                "decision": "approved",
                "by": f"person-{index}",
                "at": "2026-10-29",
            },
        ).status_code

    with ThreadPoolExecutor(writers) as pool:
        codes = list(pool.map(approve, range(writers)))

    assert codes == [200] * writers
    stored = test_client.get(f"/runs/{run_id}").json()
    assert len(stored["approvals"]) == writers
    verdict = _integrity(test_client)
    assert verdict["intact"], verdict["summary"]


# --- what an edit short of a whole-chain rewrite looks like, and that each one is named ------


def test_deleting_the_last_run_and_its_entry_is_reported_as_a_truncated_tail(
    test_client, engine
) -> None:
    """The head anchor is what makes the cut visible: without it, a shorter chain that still
    recomputes reads as intact, which is exactly how an unflattering run used to vanish."""
    run_ids = [_post(test_client, item=item) for item in ("a", "b", "c")]
    with Session(engine) as session:
        session.delete(session.get(RunRecord, run_ids[-1]))
        last = session.exec(
            select(AuditEntry).order_by(col(AuditEntry.seq).desc()).limit(1)
        ).one()
        session.delete(last)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["head_seq"] == 3
    assert "head" in verdict["summary"]


def test_removing_a_label_by_deleting_its_entry_and_reverting_the_row_is_detected(
    test_client, engine
) -> None:
    run_id = _post(test_client)
    test_client.post(
        f"/runs/{run_id}/label",
        json={"resolved": False, "label_source": LabelSource.OFFICIAL_HARNESS.value},
    )
    with Session(engine) as session:
        last = session.exec(
            select(AuditEntry).order_by(col(AuditEntry.seq).desc()).limit(1)
        ).one()
        session.delete(last)
        record = session.get(RunRecord, run_id)
        record.resolved = None
        record.label_source = LabelSource.UNLABELLED
        record.labelled_at = None
        session.add(record)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["head_seq"] == 2


def test_rewriting_an_entrys_event_breaks_the_chain(test_client, engine) -> None:
    _post(test_client, item="a")
    _post(test_client, item="b")
    with Session(engine) as session:
        entry = session.exec(select(AuditEntry).where(AuditEntry.seq == 1)).one()
        entry.event = "approved"
        session.add(entry)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["first_broken_entry"] == 0


def test_rewriting_an_entrys_timestamp_breaks_the_chain(test_client, engine) -> None:
    _post(test_client, item="a")
    _post(test_client, item="b")
    with Session(engine) as session:
        entry = session.exec(select(AuditEntry).where(AuditEntry.seq == 1)).one()
        entry.at = entry.at - timedelta(days=30)
        session.add(entry)
        session.commit()

    assert not _integrity(test_client)["intact"]


def test_forging_the_fields_the_old_scheme_never_hashed_is_detected(
    test_client, engine
) -> None:
    """component_versions is what the epoch pooling turns on, the transcript is what a run is,
    and the token counts are what a cost claim cites. None of them was covered before."""
    run_id = _post(test_client)
    with Session(engine) as session:
        record = session.get(RunRecord, run_id)
        record.component_versions = {"vllm": "9.9"}
        record.prompt_tokens = 10**6
        record.messages = [{"role": "user", "content": "forged"}]
        record.extra = {"x": 1}
        session.add(record)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["altered_runs"] == [run_id]


def test_forging_a_mid_chain_entry_takes_more_than_one_recomputed_hash(
    test_client, engine
) -> None:
    """The forger recomputes the entry's own hash, which used to be the whole cost of a forgery.
    Every later entry's hash covers this one, so the chain still breaks — one step later."""
    for item in ("a", "b", "c"):
        _post(test_client, item=item)
    with Session(engine) as session:
        first, middle = (
            session.exec(select(AuditEntry).where(AuditEntry.seq == n)).one()
            for n in (1, 2)
        )
        middle.audit_fields = {**middle.audit_fields, "resolved": True}
        middle.hash = entry_hash(
            middle.chain_seq,
            middle.run_id,
            middle.event,
            middle.at,
            middle.audit_fields,
            middle.digests,
            first.hash,
            middle.actor,
        )
        session.add(middle)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["first_broken_entry"] == 2


def test_a_deleted_run_row_whose_entries_remain_is_reported_as_orphaned(
    test_client, engine
) -> None:
    run_id = _post(test_client)
    _post(test_client, item="stays")
    with Session(engine) as session:
        session.delete(session.get(RunRecord, run_id))
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["orphaned_entries"] == [run_id]
    assert "no longer have a row" in verdict["summary"]


def test_the_endpoint_reports_what_it_verified(test_client) -> None:
    run_id = _post(test_client)
    test_client.post(
        f"/runs/{run_id}/label",
        json={"resolved": True, "label_source": LabelSource.OFFICIAL_HARNESS.value},
    )

    verdict = _integrity(test_client)

    assert verdict["intact"]
    assert (verdict["entries_checked"], verdict["runs_checked"]) == (2, 1)
    assert verdict["head_seq"] == 2
    assert verdict["erased_runs"] == []


def test_a_deleted_head_reads_as_truncation_not_as_intact(test_client, engine) -> None:
    """Removing the anchor with the tail is the next move an editor would try."""
    _post(test_client)
    with Session(engine) as session:
        session.delete(session.get(ChainHead, "hpml"))
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["head_seq"] is None
    assert "no recorded head" in verdict["summary"]


# --- who made each change ---------------------------------------------------------------------


def test_the_history_of_a_run_lists_each_change_with_who_made_it(test_client) -> None:
    run_id = _post(test_client)
    test_client.post(
        f"/runs/{run_id}/label",
        json={"resolved": True, "label_source": LabelSource.OFFICIAL_HARNESS.value},
    )
    test_client.post(
        f"/runs/{run_id}/approvals",
        json={"action": "push", "decision": "approved", "by": "x", "at": "now"},
    )

    history = test_client.get(f"/runs/{run_id}/history").json()

    assert [h["event"] for h in history] == ["created", "labelled", "approved"]
    assert [h["seq"] for h in history] == [1, 2, 3]
    # AUTH=none: the log says the service was open rather than inventing a caller.
    assert {h["actor"] for h in history} == {"anonymous"}
    assert all(h["at"].endswith("+00:00") or h["at"].endswith("Z") for h in history)


def test_the_history_of_another_tenants_run_is_not_found(test_client) -> None:
    assert test_client.get("/runs/nope/history").status_code == 404


def test_an_entry_whose_actor_is_rewritten_breaks_the_chain(
    test_client, engine
) -> None:
    """The actor is in the hash: a change cannot be re-attributed afterwards."""
    _post(test_client, item="a")
    _post(test_client, item="b")
    with Session(engine) as session:
        second = session.exec(select(AuditEntry).where(AuditEntry.seq == 2)).one()
        second.actor = "someone-else"
        session.add(second)
        session.commit()

    verdict = _integrity(test_client)

    assert not verdict["intact"]
    assert verdict["first_broken_entry"] == 1


def test_an_entry_written_before_the_log_named_actors_still_verifies(engine) -> None:
    """Entries from before 0.11 carry no actor; the hash leaves an empty one out."""
    record = RunRecord(tenant="hpml", item="a", arm="baseline")
    with Session(engine) as session:
        session.add(record)
        audit.append(session, record, "created")
        session.commit()
        assert session.exec(select(AuditEntry)).one().actor == ""
        verdict = audit.verify(session, "hpml")

    assert verdict.intact
