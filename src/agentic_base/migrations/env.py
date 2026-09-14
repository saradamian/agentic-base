"""How Alembic reaches the database and the models. Run by Alembic, not imported."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool
from sqlmodel import SQLModel

import agentic_base.domain.audit  # noqa: F401  - registers the audit log
import agentic_base.domain.run_record  # noqa: F401  - registers the run table

config = context.config
target_metadata = SQLModel.metadata


def run_offline() -> None:
    # Batch mode lets SQLite, which cannot alter a column in place, take the same migrations.
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        render_as_batch=True,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = create_engine(
        str(config.get_main_option("sqlalchemy.url")), poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
