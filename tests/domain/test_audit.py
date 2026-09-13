"""The audit log the service writes, and what verifying it catches."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from agentic_base.domain import audit
from agentic_base.domain.audit import AuditEntry
from agentic_base.domain.integrity import GENESIS, hash_snapshot, snapshot
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


def test_two_entries_cannot_chain_to_the_same_predecessor(engine) -> None:
    record = RunRecord(tenant="hpml", item="a", arm="baseline")
    values = snapshot(record)
    with Session(engine) as session:
        session.add(record)
        audit.append(session, record, "created")
        session.commit()
        session.add(
            AuditEntry(
                tenant="hpml",
                run_id=record.run_id,
                event="forged",
                audit_fields=values,
                previous_hash=GENESIS,
                hash=hash_snapshot(values),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_a_write_that_loses_the_race_is_refused_not_written(
    test_client, monkeypatch
) -> None:
    _post(test_client, item="first")

    def stale(session, record, event):
        values = snapshot(record)
        entry = AuditEntry(
            tenant=record.tenant,
            run_id=record.run_id,
            event=event,
            audit_fields=values,
            previous_hash=GENESIS,
            hash=hash_snapshot(values),
        )
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
