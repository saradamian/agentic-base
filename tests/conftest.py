import pytest
from fastapi.testclient import TestClient

from app.db import get_engine
from app.main import get_app


@pytest.fixture(scope="session", autouse=True)
def _dispose_engine():
    """The test client never enters the app lifespan, so nothing else closes the pool.

    Python 3.13+ reports a sqlite connection finalised open, and the suite treats warnings as
    errors, so an undisposed engine fails the run on the newest interpreter only.
    """
    yield
    get_engine().dispose()


@pytest.fixture(scope="session")
def app():
    return get_app()


@pytest.fixture()
def test_client(app):
    return TestClient(app)
