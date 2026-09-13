"""Fixtures for the service tests.

Every test gets its own empty database, in a temporary directory. The alternative, one file in
the working directory, fails in a way that reads exactly like a code regression: add a column and
every local run reports `table run_record has no column named principal`, from yesterday's file,
while continuous integration stays green because its container is fresh. It cost two people an
afternoon between them.

Two things point at a temporary directory, because two things open a database. Each test's own
file is supplied by overriding the session dependency, which is the isolation that matters.
Building the application also creates tables through the cached engine, so the settings are
pointed at a temporary file once for the session before that happens; otherwise merely importing
the application writes into the working directory.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from agentic_base.config import get_settings
from agentic_base.db import get_engine, get_session
from agentic_base.main import get_app


@pytest.fixture(scope="session", autouse=True)
def _service_database(tmp_path_factory):
    """The application's own engine, out of the working directory and gone at the end."""
    os.environ["DATABASE_URL"] = (
        f"sqlite:///{tmp_path_factory.mktemp('service') / 'service.db'}"
    )
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_engine().dispose()


@pytest.fixture(scope="session")
def app(_service_database):
    return get_app()


@pytest.fixture()
def engine(tmp_path):
    """A fresh SQLite file per test, created from the current models and disposed afterwards."""
    import agentic_base.domain.audit  # noqa: F401  - registers the audit log
    import agentic_base.domain.run_record  # noqa: F401  - registers the table

    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    # Python 3.13+ reports a sqlite connection finalised open, and the suite treats warnings as
    # errors, so an undisposed engine fails the run on the newest interpreter only.
    engine.dispose()


@pytest.fixture()
def test_client(app, engine) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session)
