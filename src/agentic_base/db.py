"""Database wiring.

SQLModel over PostgreSQL in every deployed environment, which the platform provides as a
tenant resource. SQLite is the local-development and test default so the service can be run
and tested without infrastructure.
"""

from collections.abc import Iterator
from functools import cache

from sqlmodel import Session, create_engine

from agentic_base.config import get_settings


@cache
def get_engine():  # noqa: ANN201 - engine type is a SQLAlchemy internal
    """Create the process-wide engine."""
    settings = get_settings()
    connect_args = (
        {"check_same_thread": False}
        if settings.database_url.startswith("sqlite")
        else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args)


def init_db() -> None:
    """Bring the database to the schema this build needs, or refuse to start.

    A local SQLite file is migrated in place; any other database must already be current. See
    :mod:`agentic_base.migrations`.
    """
    from agentic_base.migrations.schema import ensure_current

    ensure_current(get_engine(), get_settings().database_url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session."""
    with Session(get_engine()) as session:
        yield session
