"""Retry policy and transport recycling."""

import httpx

from agentic_base.llm.resilience import (
    TransportPool,
    is_wrapped_timeout,
    should_retry_exception,
    should_retry_status,
)


def test_gateway_statuses_from_a_restarting_backend_are_retried() -> None:
    assert all(should_retry_status(code) for code in (502, 503, 504))


def test_rate_limiting_is_retried() -> None:
    assert should_retry_status(429)


def test_a_server_error_is_not_retried_because_it_is_a_request_fault() -> None:
    assert not should_retry_status(500)


def test_client_errors_are_not_retried() -> None:
    assert not any(should_retry_status(code) for code in (400, 401, 403, 404, 422))


def test_a_timeout_is_retried() -> None:
    assert should_retry_exception(httpx.ReadTimeout("slow"))


def test_a_connection_error_is_retried_because_it_is_the_dead_pool_signature() -> None:
    assert should_retry_exception(httpx.ConnectError("refused"))


def test_an_unrelated_exception_is_not_retried() -> None:
    assert not should_retry_exception(ValueError("bad input"))


def test_a_gateway_wrapping_a_timeout_as_a_client_error_is_recognised() -> None:
    """One gateway in front of our models returns an internal read timeout as a 400."""
    assert is_wrapped_timeout("httpx.ReadTimeout: timed out")
    assert is_wrapped_timeout("internal readtimeout")
    assert not is_wrapped_timeout("max_tokens is too large")


def test_recycling_discards_the_client_so_the_next_call_opens_fresh_connections() -> (
    None
):
    created: list[httpx.Client] = []

    def factory() -> httpx.Client:
        client = httpx.Client()
        created.append(client)
        return client

    pool = TransportPool(factory)
    first = pool.client
    pool.recycle()
    second = pool.client

    assert first is not second
    assert pool.recycles == 1
    assert first.is_closed
    pool.close()


def test_recycling_before_any_use_does_not_count_as_a_recycle() -> None:
    pool = TransportPool(httpx.Client)

    pool.recycle()

    assert pool.recycles == 0
