from http import HTTPStatus
from typing import Never

import pytest
from structlog.testing import capture_logs

from app.utils.logging import drop_color_message_key

TEST_CLIENT_PORT = 50000


def test_drop_color_message_key():
    assert drop_color_message_key(None, "", {"a": 1, "color_message": ""}) == {"a": 1}


@pytest.mark.asyncio
async def test_logs(test_client):
    with capture_logs() as cap_logs:
        test_client.get("/docs")

    assert len(cap_logs) == 1
    log_message = cap_logs[0]
    assert (
        log_message["event"]
        == f'testclient:{TEST_CLIENT_PORT} - "GET /docs HTTP/1.1" 200'
    )

    assert log_message["log_level"] == "info"
    assert log_message["duration"] > 0
    assert log_message["http"]["url"] == "http://testserver/docs"
    assert log_message["http"]["status_code"] == HTTPStatus.OK
    assert log_message["http"]["method"] == "GET"
    assert log_message["http"]["request_id"] is not None
    assert log_message["http"]["version"] == "1.1"
    assert log_message["network"]["client"]["ip"] == "testclient"
    assert log_message["network"]["client"]["port"] == TEST_CLIENT_PORT


@pytest.mark.asyncio
async def test_logs_for_not_found_route(test_client):
    with capture_logs() as cap_logs:
        test_client.get("/path-not-found")

    assert len(cap_logs) == 1
    log_message = cap_logs[0]
    assert (
        log_message["event"]
        == f'testclient:{TEST_CLIENT_PORT} - "GET /path-not-found HTTP/1.1" 404'
    )

    assert log_message["log_level"] == "info"
    assert log_message["duration"] > 0
    assert log_message["http"]["url"] == "http://testserver/path-not-found"
    assert log_message["http"]["status_code"] == HTTPStatus.NOT_FOUND
    assert log_message["http"]["method"] == "GET"
    assert log_message["http"]["request_id"] is not None
    assert log_message["http"]["version"] == "1.1"
    assert log_message["network"]["client"]["ip"] == "testclient"
    assert log_message["network"]["client"]["port"] == TEST_CLIENT_PORT


@pytest.mark.asyncio
async def test_logs_for_ignored_route(test_client):
    with capture_logs() as cap_logs:
        test_client.get("/health/readiness")

    assert len(cap_logs) == 0


@pytest.mark.asyncio
async def test_logs_ise(app, test_client):
    @app.get("/ise", response_model=None)
    async def ise() -> Never:
        raise ValueError("AAAAA!")

    with pytest.raises(ValueError, match="AAAAA!"), capture_logs() as cap_logs:
        test_client.get("/ise")

    assert len(cap_logs) == 2  # noqa: PLR2004
    log_message = cap_logs[0]
    assert log_message["event"] == "Uncaught exception"
    assert log_message["log_level"] == "error"

    log_message = cap_logs[1]
    assert (
        log_message["event"]
        == f'testclient:{TEST_CLIENT_PORT} - "GET /ise HTTP/1.1" 500'
    )
    assert log_message["log_level"] == "info"
    assert log_message["duration"] > 0
    assert log_message["http"]["url"] == "http://testserver/ise"
    assert log_message["http"]["status_code"] == HTTPStatus.INTERNAL_SERVER_ERROR
    assert log_message["http"]["method"] == "GET"
    assert log_message["http"]["request_id"] is not None
    assert log_message["http"]["version"] == "1.1"
    assert log_message["network"]["client"]["ip"] == "testclient"
    assert log_message["network"]["client"]["port"] == TEST_CLIENT_PORT
