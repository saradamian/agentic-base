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
    from agentic_base.config import get_settings
    from agentic_base.db import get_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'cmd.sqlite'}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    try:
        main()
        main()
    finally:
        get_engine().dispose()
        monkeypatch.undo()
        get_settings.cache_clear()
        get_engine.cache_clear()

    assert capsys.readouterr().out.splitlines() == [
        f"database schema: empty -> {head_revision()}",
        f"database schema: {head_revision()} -> {head_revision()}",
    ]
