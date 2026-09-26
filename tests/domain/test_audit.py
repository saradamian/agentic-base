"""The audit log the service writes, and what verifying it catches."""

from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from agentic_base.domain import audit
from agentic_base.domain.audit import AuditEntry, ChainHead
from agentic_base.domain.integrity import (
    GENESIS,
    entry_hash,
    field_digests,
    snapshot,
)
from agentic_base.domain.run_record import LabelSource, RunRecord


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

    def stale(session, record, event):
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
