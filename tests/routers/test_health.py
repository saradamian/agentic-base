from http import HTTPStatus

from app.routers.health import HealthStatus


def test_liveness(test_client):
    response = test_client.get("/health/liveness")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": HealthStatus.UP}


def test_readiness(test_client):
    response = test_client.get("/health/readiness")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": HealthStatus.UP}
