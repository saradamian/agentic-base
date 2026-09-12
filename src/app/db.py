"""Database wiring.

SQLModel over PostgreSQL in every deployed environment, which the platform provides as a
tenant resource. SQLite is the local-development and test default so the service can be run
and tested without infrastructure.
"""

from collections.abc import Iterator
from functools import cache

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


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
    """Create tables that do not exist yet.

    Schema evolution in a deployed environment is Alembic's job. This exists so that local
    runs and tests do not need a migration step.
    """
    import app.domain.run_record  # noqa: F401  - registers the table

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session."""
    with Session(get_engine()) as session:
        yield session
