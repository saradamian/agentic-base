"""Outbound request safety.

An agent that fetches a URL for a user is a request-forgery primitive unless something checks the
target. Inside a cluster the reachable set includes the scheduler API, cloud metadata endpoints,
and every internal service on the network.
"""

import ipaddress

import pytest

from app.security import netsec


def test_a_public_address_literal_is_allowed() -> None:
    assert netsec.is_url_safe("https://93.184.216.34/x")[0]


def test_a_loopback_address_is_refused() -> None:
    ok, reason = netsec.is_url_safe("http://127.0.0.1:80/admin")

    assert not ok
    assert "disallowed address" in reason


@pytest.mark.parametrize(
    "host", ["10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254", "[::1]"]
)
def test_private_link_local_and_metadata_addresses_are_refused(host: str) -> None:
    """169.254.169.254 is the cloud metadata endpoint and the usual target of these attacks."""
    assert not netsec.is_url_safe(f"http://{host}/")[0]


def test_a_non_http_scheme_is_refused() -> None:
    ok, reason = netsec.is_url_safe("file:///etc/passwd")

    assert not ok
    assert "scheme" in reason


def test_credentials_in_the_authority_are_refused() -> None:
    """A URL carrying a credential is either an exfiltration path or a mistake."""
    ok, reason = netsec.is_url_safe("https://user:secret@example.com/")

    assert not ok
    assert "credentials" in reason


def test_an_unusual_port_is_refused() -> None:
    ok, reason = netsec.is_url_safe("https://example.com:6443/api", resolve_dns=False)

    assert not ok
    assert "port 6443" in reason


def test_an_empty_hostname_is_refused() -> None:
    assert not netsec.is_url_safe("https:///path")[0]


def test_a_name_resolving_to_a_private_address_is_refused(monkeypatch) -> None:
    """The usual bypass: a public name pointing at an internal address."""
    monkeypatch.setattr(netsec, "resolve", lambda host: [ipaddress.ip_address("10.1.2.3")])

    ok, reason = netsec.is_url_safe("https://sneaky.example.com/")

    assert not ok
    assert "disallowed address" in reason


def test_a_name_that_does_not_resolve_is_refused_rather_than_allowed(monkeypatch) -> None:
    """A check that could not run must not report a pass."""
    monkeypatch.setattr(netsec, "resolve", lambda host: [])

    ok, reason = netsec.is_url_safe("https://nowhere.example.com/")

    assert not ok
    assert "could not resolve" in reason


def test_a_name_resolving_only_to_public_addresses_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(netsec, "resolve", lambda host: [ipaddress.ip_address("93.184.216.34")])

    assert netsec.is_url_safe("https://example.com/")[0]


def test_every_resolved_address_is_checked_not_only_the_first(monkeypatch) -> None:
    """A host with one public and one private address is still a way in."""
    monkeypatch.setattr(
        netsec,
        "resolve",
        lambda host: [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.0.0.1")],
    )

    assert not netsec.is_url_safe("https://mixed.example.com/")[0]


def test_validate_url_raises_for_an_unsafe_target() -> None:
    with pytest.raises(netsec.URLSafetyError):
        netsec.validate_url("http://127.0.0.1/")


def test_validate_url_is_silent_for_a_safe_target() -> None:
    assert netsec.validate_url("https://93.184.216.34/") is None
