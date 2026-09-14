"""Upgrade a database to the newest schema, and refuse to serve against an older one."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect

HERE = Path(__file__).resolve().parent


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(HERE))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision() -> str:
    head = ScriptDirectory(str(HERE)).get_current_head()
    assert head is not None, "the migrations directory has no revision"
    return head


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


class SchemaNotCurrent(RuntimeError):
    """The database is not at the revision this build needs."""


def ensure_current(engine: Engine, database_url: str) -> None:
    """Migrate a local SQLite database; refuse to run against any other database that is behind.

    A database with tables and no revision predates migrations. It is refused on every backend,
    because stamping it as current would be a claim about its columns that nothing checked.
    """
    head = head_revision()
    current = current_revision(engine)
    if current is None and inspect(engine).get_table_names():
        raise SchemaNotCurrent(
            "the database has tables but no migration revision, so it predates migrations. "
            "A local SQLite file can be deleted; anything else needs its schema compared with "
            "the models before it is stamped with `alembic stamp`."
        )
    if current == head:
        return
    if engine.dialect.name == "sqlite":
        upgrade(database_url)
        return
    raise SchemaNotCurrent(
        f"the database schema is at revision {current or 'none'} and this build needs {head}: "
        "run `agentic-base-migrate` before starting the service"
    )


def main() -> None:
    """The ``agentic-base-migrate`` command: upgrade the configured database to the newest schema."""
    from agentic_base.config import get_settings
    from agentic_base.db import get_engine

    url = get_settings().database_url
    before = current_revision(get_engine())
    upgrade(url)
    after = current_revision(get_engine())
    print(f"database schema: {before or 'empty'} -> {after}")


if __name__ == "__main__":
    main()
