import pytest
from fastapi.testclient import TestClient

from app.main import get_app


@pytest.fixture(scope="session")
def app():
    return get_app()


@pytest.fixture()
def test_client(app):
    return TestClient(app)
