"""The migrations build exactly the schema the models describe, and the service checks it."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, Enum, MetaData, String, create_engine
from sqlmodel import SQLModel

import agentic_base.domain.audit  # noqa: F401
import agentic_base.domain.run_record  # noqa: F401
from agentic_base.migrations.schema import (
    SchemaNotCurrent,
    alembic_config,
    current_revision,
    ensure_current,
    head_revision,
    main,
    upgrade,
)


def _differences(url: str, metadata: MetaData) -> list:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return compare_metadata(MigrationContext.configure(connection), metadata)
    finally:
        engine.dispose()


def test_migrating_an_empty_database_builds_exactly_the_models(tmp_path) -> None:
    """A model changed without a migration makes this list non-empty."""
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"

    upgrade(url)

    assert _differences(url, SQLModel.metadata) == []


def test_the_comparison_notices_a_column_the_migrations_do_not_have(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    upgrade(url)
    changed = MetaData()
    for table in SQLModel.metadata.tables.values():
        table.to_metadata(changed)
    changed.tables["run_record"].append_column(
        Column("added_later", String(), nullable=True)
    )

    assert _differences(url, changed) != []


def test_the_migrations_run_down_and_up_again(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    config = alembic_config(url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    assert _differences(url, SQLModel.metadata) == []


def test_no_column_is_a_database_enum_type() -> None:
    """A database enum needs a migration to gain a member, and no table comparison notices."""
    enums = [
        (table.name, column.name, column.type)
        for table in SQLModel.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Enum)
    ]

    assert enums
    for table, column, kind in enums:
        assert kind.native_enum is False, f"{table}.{column}"
        assert kind.create_constraint is False, f"{table}.{column}"


def test_a_local_database_is_migrated_on_start(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)

    ensure_current(engine, url)

    assert current_revision(engine) == head_revision()
    engine.dispose()


def test_a_database_that_predates_migrations_is_refused(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)

    with pytest.raises(SchemaNotCurrent, match="predates migrations"):
        ensure_current(engine, url)
    engine.dispose()


def test_a_shared_database_that_is_behind_is_refused_not_migrated(
    tmp_path, monkeypatch
) -> None:
    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_engine(url)
    monkeypatch.setattr(engine.dialect, "name", "postgresql")

    with pytest.raises(SchemaNotCurrent, match="agentic-base-migrate"):
        ensure_current(engine, url)
    assert current_revision(engine) is None
    engine.dispose()


def test_the_command_upgrades_the_configured_database(
    tmp_path, monkeypatch, capsys
) -> None:
    """Pointed at its own settings and engine, not by clearing the shared caches: clearing them
    drops the session's engine undisposed, and its pooled connections are then finalised open at
    some later garbage collection, which Python 3.13+ reports against whichever test is running."""
    import agentic_base.config as config_module
    import agentic_base.db as db_module
    from agentic_base.config import Settings

    url = f"sqlite:///{tmp_path / 'cmd.sqlite'}"
    engine = create_engine(url)
    monkeypatch.setattr(
        config_module, "get_settings", lambda: Settings(database_url=url)
    )
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    try:
        main()
        main()
    finally:
        engine.dispose()

    assert capsys.readouterr().out.splitlines() == [
        f"database schema: empty -> {head_revision()}",
        f"database schema: {head_revision()} -> {head_revision()}",
    ]


def test_the_second_migration_rewrites_an_existing_log_and_drops_the_person_from_it(
    tmp_path,
) -> None:
    """A pre-0002 log holds principal and approvals in every snapshot and its hashes cover
    neither position nor head. After the migration the person is out of the log, every entry
    verifies under the entry scheme, the head is anchored, and an honestly-claimed erasure
    got its stamp — while a run row that never had an entry stays flagged, not legitimised."""
    from datetime import datetime, timezone

    from sqlmodel import Session

    from agentic_base.domain import audit

    url = f"sqlite:///{tmp_path / 'db.sqlite'}"
    config = alembic_config(url)
    command.upgrade(config, "0001")

    engine = create_engine(url)
    reflected = MetaData()
    reflected.reflect(bind=engine)
    runs, entries = reflected.tables["run_record"], reflected.tables["audit_entry"]
    created = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    def run_row(run_id: str, item: str, **overrides) -> dict:
        row = {
            "run_id": run_id,
            "created_at": created,
            "tenant": "hpml",
            "item": item,
            "arm": "baseline",
            "arm_fingerprint": "",
            "system_prompt": "acting for Maria Jansen",
            "messages": [{"role": "user", "content": "hello"}],
            "model": "",
            "endpoint": "",
            "precision": "",
            "code_revision": "abc",
            "principal": "Maria Jansen",
            "classification": "unclassified",
            "isolation_tier": "unspecified",
            "redaction": "none",
            "disclosure": "none",
            "content_marking": "none",
            "approvals": [],
            "component_versions": {},
            "status": "completed",
            "failure_kind": "",
            "resolved": None,
            "label_source": "unlabelled",
            "labelled_at": None,
            "degraded": False,
            "instrument": "",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "joules": 0.0,
            "num_steps": 0,
            "total_tool_calls": 0,
            "elapsed_ms": 0.0,
            "extra": {},
        }
        row.update(overrides)
        return row

    with engine.begin() as connection:
        connection.execute(
            runs.insert(),
            [
                run_row("r1", "a"),
                run_row(
                    "r2",
                    "b",
                    system_prompt="",
                    messages=[],
                    principal="",
                    extra={
                        "erasure": {
                            "at": "2026-09-02T00:00:00+00:00",
                            "reason": "the person asked",
                            "fields": ["system_prompt", "messages"],
                        }
                    },
                ),
                run_row("r3", "smuggled"),
            ],
        )
        connection.execute(
            entries.insert(),
            [
                {
                    "tenant": "hpml",
                    "run_id": "r1",
                    "event": "created",
                    "at": created,
                    "audit_fields": {
                        "run_id": "r1",
                        "principal": "Maria Jansen",
                        "approvals": [],
                    },
                    "previous_hash": "0" * 64,
                    "hash": "a" * 64,
                },
                {
                    "tenant": "hpml",
                    "run_id": "r2",
                    "event": "created",
                    "at": created,
                    "audit_fields": {"run_id": "r2", "principal": "", "approvals": []},
                    "previous_hash": "a" * 64,
                    "hash": "b" * 64,
                },
            ],
        )
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(url)
    with Session(engine) as session:
        verdict = audit.verify(session, "hpml")
    with engine.connect() as connection:
        log = " ".join(
            str(row)
            for row in connection.exec_driver_sql('SELECT * FROM "audit_entry"')
        )
        (erased_at,) = connection.exec_driver_sql(
            "SELECT erased_at FROM run_record WHERE run_id = 'r2'"
        ).one()
    engine.dispose()

    assert "Maria Jansen" not in log
    assert verdict.chain.intact, verdict.summary()
    assert verdict.chain.records_checked == 4  # two rewritten, two migrated
    assert verdict.head_seq == 4
    assert verdict.erased == ["r2"]
    assert erased_at is not None
    assert verdict.unchained == ["r3"]
    assert not verdict.intact  # the smuggled row stays a finding
