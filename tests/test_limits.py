"""Limits resolve when they are read, not when the module is imported."""

import pytest

from app.limits import Limits, get_limits


@pytest.fixture(autouse=True)
def _clear_cache():
    get_limits.cache_clear()
    yield
    get_limits.cache_clear()


def test_a_limit_falls_back_to_its_declared_default() -> None:
    assert get_limits().validity_spread_ratio == 2.0


def test_an_environment_value_reaches_the_limit(monkeypatch) -> None:
    """The failure this guards: constants resolved at import time ignore anything layered after.

    In the predecessor project, environment values for every limit were silently dropped unless
    some other module happened to import the configuration first.
    """
    monkeypatch.setenv("AP_MCP_MAX_ROWS", "17")

    assert get_limits().mcp_max_rows == 17


def test_the_environment_prefix_is_namespaced(monkeypatch) -> None:
    """A bare name would collide with whatever else is in a container's environment."""
    monkeypatch.setenv("MCP_MAX_ROWS", "999")

    assert get_limits().mcp_max_rows != 999


def test_clearing_the_cache_picks_up_a_change(monkeypatch) -> None:
    first = get_limits().fetch_timeout_s
    monkeypatch.setenv("AP_FETCH_TIMEOUT_S", str(first + 5))
    get_limits.cache_clear()

    assert get_limits().fetch_timeout_s == first + 5


def test_every_limit_carries_a_default_so_the_service_starts_with_no_configuration() -> (
    None
):
    """A platform component that will not start without a full environment is a deployment risk."""
    assert Limits()
