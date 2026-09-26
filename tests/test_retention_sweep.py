"""Running retention against the database: what is erased, what is left, and what the log says."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from agentic_base.domain import audit
from agentic_base.domain.audit import AuditEntry
from agentic_base.domain.run_record import RunRecord
from agentic_base.retention_sweep import (
    erase_run,
    main,
    parse_policies,
    sweep,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _add(session: Session, tenant: str, days_old: int, item: str) -> str:
    record = RunRecord(
        tenant=tenant,
        item=item,
        created_at=NOW - timedelta(days=days_old),
        system_prompt="you are careful",
        messages=[{"role": "user", "content": "private details"}],
    )
    session.add(record)
    audit.append(session, record, "created")
    session.commit()
    return record.run_id


def _get(engine, run_id: str) -> RunRecord:
    with Session(engine) as session:
        record = session.get(RunRecord, run_id)
        assert record is not None
        return record


@pytest.fixture()
def corpus(engine):
    with Session(engine) as session:
        return {
            "old": _add(session, "team-a", 400, "old"),
            "recent": _add(session, "team-a", 10, "recent"),
            "other-old": _add(session, "team-b", 400, "other-old"),
        }


def test_a_dry_run_reports_what_is_due_and_changes_nothing(engine, corpus) -> None:
    with Session(engine) as session:
        done, skipped = sweep(
            session, parse_policies('{"team-a": 365}'), NOW, apply=False
        )

    (team_a,) = done
    assert (team_a.examined, team_a.due, team_a.erased) == (2, 1, 0)
    assert skipped == ["team-b"]
    assert _get(engine, corpus["old"]).messages != []


def test_applying_erases_only_due_transcripts_and_the_log_still_verifies(
    engine, corpus
) -> None:
    with Session(engine) as session:
        sweep(session, parse_policies('{"team-a": 365}'), NOW, apply=True)

    old, recent = _get(engine, corpus["old"]), _get(engine, corpus["recent"])
    assert (old.system_prompt, old.messages) == ("", [])
    assert old.extra["erasure"]["reason"] == "retention policy: kept 365 days"
    assert recent.messages != []
    with Session(engine) as session:
        verdict = audit.verify(session, "team-a")
        events = [e.event for e in session.exec(select(AuditEntry)).all()]
    assert verdict.intact, verdict.summary()
    assert events.count("erased") == 1


def test_a_second_sweep_finds_the_erasure_already_done(engine, corpus) -> None:
    policies = parse_policies('{"team-a": 365}')
    with Session(engine) as session:
        sweep(session, policies, NOW, apply=True)
        (again,), _ = sweep(session, policies, NOW, apply=True)

    assert (again.due, again.erased, again.already_erased) == (1, 0, 1)


def test_a_tenant_with_no_policy_is_skipped_and_named_not_erased(
    engine, corpus
) -> None:
    with Session(engine) as session:
        _, skipped = sweep(session, parse_policies('{"team-a": 365}'), NOW, apply=True)

    assert skipped == ["team-b"]
    assert _get(engine, corpus["other-old"]).messages != []


def test_a_default_policy_covers_unnamed_tenants_and_a_named_one_overrides_it(
    engine, corpus
) -> None:
    with Session(engine) as session:
        done, skipped = sweep(
            session, parse_policies('{"*": 365, "team-a": 500}'), NOW, apply=True
        )

    assert skipped == []
    assert _get(engine, corpus["other-old"]).messages == []
    assert _get(engine, corpus["old"]).messages != []  # 400 days is inside team-a's 500


def test_an_erasure_on_request_ignores_age_and_happens_once(engine, corpus) -> None:
    with Session(engine) as session:
        first = erase_run(session, corpus["recent"], "the person asked", NOW)
        second = erase_run(session, corpus["recent"], "the person asked", NOW)
        verdict = audit.verify(session, "team-a")

    assert (first, second) == (True, False)
    assert (
        _get(engine, corpus["recent"]).extra["erasure"]["reason"] == "the person asked"
    )
    assert verdict.intact


def test_an_unknown_run_cannot_be_erased(engine) -> None:
    with Session(engine) as session, pytest.raises(LookupError):
        erase_run(session, "nope", "asked", NOW)


def test_a_stored_scorerless_label_does_not_stop_the_rest_of_the_sweep(
    engine, corpus, caplog
) -> None:
    """One row the create rules would refuse, written straight to the database, must cost
    its own erasure and nothing else's."""
    import logging

    from agentic_base.domain.run_record import LabelSource

    with Session(engine) as session:
        bad = RunRecord(
            tenant="team-a",
            item="poisoned",
            created_at=NOW - timedelta(days=400),
            messages=[{"role": "user", "content": "private details"}],
            resolved=True,
            label_source=LabelSource.UNLABELLED,
        )
        session.add(bad)
        session.commit()
        bad_id = bad.run_id

    with (
        caplog.at_level(logging.WARNING, logger="agentic_base.domain.run_record"),
        Session(engine) as session,
    ):
        done, _ = sweep(session, parse_policies('{"team-a": 365}'), NOW, apply=True)

    (team_a,) = done
    assert (team_a.due, team_a.erased, team_a.invalid) == (2, 1, 1)
    assert "skipped 1" in team_a.describe(True)
    assert _get(engine, corpus["old"]).messages == []
    assert _get(engine, bad_id).messages != []
    assert any(bad_id in message for message in caplog.messages)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{nope", "not valid JSON"),
        ('{"team-a": "365"}', "whole days"),
        ('{"team-a": true}', "whole days"),
        ('{"team-a": 30}', "floor"),
    ],
)
def test_a_malformed_or_too_short_policy_refuses_the_run(raw, message) -> None:
    with pytest.raises(ValueError, match=message):
        parse_policies(raw)


def test_the_command_reports_a_dry_run_then_erases(
    engine, corpus, monkeypatch, capsys
) -> None:
    import agentic_base.config as config_module
    import agentic_base.db as db_module
    from agentic_base.config import Settings

    settings = Settings(retention_policies='{"*": 365}')
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    monkeypatch.setattr(db_module, "init_db", lambda: None)

    assert main(["sweep"]) == 0
    assert main(["sweep", "--apply"]) == 0
    out = capsys.readouterr().out

    assert "team-a: examined 2, due 1" in out and "would erase 1" in out
    assert "dry run: nothing erased" in out
    assert "erased 1, already erased 0" in out


def test_the_command_refuses_to_sweep_with_no_policies(
    engine, monkeypatch, capsys
) -> None:
    import agentic_base.config as config_module
    import agentic_base.db as db_module
    from agentic_base.config import Settings

    monkeypatch.setattr(
        config_module, "get_settings", lambda: Settings(retention_policies="")
    )
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    monkeypatch.setattr(db_module, "init_db", lambda: None)

    assert main(["sweep", "--apply"]) == 1
    assert "no RETENTION_POLICIES" in capsys.readouterr().out


def test_a_writer_claimed_erasure_grants_no_exemption_from_the_sweep(engine) -> None:
    """`extra["erasure"]` set at write time used to skip the sweep forever, transcript and all.
    The exemption is the server's own stamp now, and this record never earned one."""
    with Session(engine) as session:
        record = RunRecord(
            tenant="team-c",
            item="claimer",
            created_at=NOW - timedelta(days=400),
            messages=[{"role": "user", "content": "private details"}],
            extra={"erasure": True},
        )
        session.add(record)
        audit.append(session, record, "created")
        session.commit()
        run_id = record.run_id

    with Session(engine) as session:
        (swept,), _ = sweep(session, parse_policies('{"team-c": 365}'), NOW, apply=True)

    assert (swept.due, swept.erased, swept.already_erased) == (1, 1, 0)
    record = _get(engine, run_id)
    assert record.messages == []
    assert record.erased_at is not None


def test_erasure_removes_the_person_everywhere_the_database_holds_them(
    test_client, engine
) -> None:
    """Erase, then read every row of every table: the person is gone — from the run, from the
    approvals, and from the audit log, which only ever held digests — and the chain still
    verifies, reporting the erasure rather than hiding it."""
    planted = ("Maria Jansen", "maria@example.org", "alice@example.org", "maria asked")
    response = test_client.post(
        "/runs",
        json={
            "tenant": "team-p",
            "code_revision": "abc1234",
            "item": "task-1",
            "system_prompt": "you are acting for Maria Jansen",
            "messages": [{"role": "user", "content": "mail maria@example.org"}],
            "principal": "Maria Jansen",
            "approvals": [
                {
                    "action": "send",
                    "decision": "approved",
                    "by": "alice@example.org",
                    "at": "2026-09-14",
                    "note": "maria asked",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["run_id"]

    with Session(engine) as session:
        assert erase_run(session, run_id, "the person asked", NOW)
        verdict = audit.verify(session, "team-p")

    with engine.connect() as connection:
        tables = [
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        ]
        dump = " ".join(
            str(row)
            for table in tables
            for row in connection.exec_driver_sql(f'SELECT * FROM "{table}"')
        )
    for text in planted:
        assert text not in dump, f"{text!r} survived the erasure"

    assert verdict.intact, verdict.summary()
    assert verdict.erased == [run_id]
    assert "1 erased" in verdict.summary()
