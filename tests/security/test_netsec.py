"""Outbound request safety.

An agent that fetches a URL for a user is a request-forgery primitive unless something checks the
target. Inside a cluster the reachable set includes the scheduler API, cloud metadata endpoints,
and every internal service on the network.
"""

import ipaddress

import pytest

from agentic_base.security import netsec


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
    monkeypatch.setattr(
        netsec, "resolve", lambda host: [ipaddress.ip_address("10.1.2.3")]
    )

    ok, reason = netsec.is_url_safe("https://sneaky.example.com/")

    assert not ok
    assert "disallowed address" in reason


def test_a_name_that_does_not_resolve_is_refused_rather_than_allowed(
    monkeypatch,
) -> None:
    """A check that could not run must not report a pass."""
    monkeypatch.setattr(netsec, "resolve", lambda host: [])

    ok, reason = netsec.is_url_safe("https://nowhere.example.com/")

    assert not ok
    assert "could not resolve" in reason


def test_a_name_resolving_only_to_public_addresses_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(
        netsec, "resolve", lambda host: [ipaddress.ip_address("93.184.216.34")]
    )

    assert netsec.is_url_safe("https://example.com/")[0]


def test_every_resolved_address_is_checked_not_only_the_first(monkeypatch) -> None:
    """A host with one public and one private address is still a way in."""
    monkeypatch.setattr(
        netsec,
        "resolve",
        lambda host: [
            ipaddress.ip_address("93.184.216.34"),
            ipaddress.ip_address("10.0.0.1"),
        ],
    )

    assert not netsec.is_url_safe("https://mixed.example.com/")[0]


def test_validate_url_raises_for_an_unsafe_target() -> None:
    with pytest.raises(netsec.URLSafetyError):
        netsec.validate_url("http://127.0.0.1/")


def test_validate_url_is_silent_for_a_safe_target() -> None:
    netsec.validate_url("https://93.184.216.34/")  # returns nothing; it must not raise


# --- fetching -------------------------------------------------------------------------------

import httpx  # noqa: E402

from agentic_base.security.netsec import (  # noqa: E402
    FetchResult,
    pin_target,
    safe_fetch_text,
)


def _client(handler) -> httpx.Client:
    """A client whose transport is a function, so no socket is ever opened."""
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _public(monkeypatch) -> None:
    monkeypatch.setattr(
        netsec, "resolve", lambda h: [ipaddress.ip_address("93.184.216.34")]
    )


def test_pinning_connects_to_the_address_while_still_addressing_the_host() -> None:
    """The check and the connection must reach the same machine.

    Resolving twice lets a host answer the first lookup with a public address and the second with
    a private one, so the fetch goes to the address that was actually approved.
    """
    target = pin_target("https://example.com/a/b?c=1", "93.184.216.34")

    assert target.connect_url == "https://93.184.216.34/a/b?c=1"
    assert target.host_header == "example.com"
    assert target.sni_hostname == "example.com"


def test_pinning_preserves_a_non_default_port() -> None:
    target = pin_target("https://example.com:443/x", "93.184.216.34")

    assert target.connect_url == "https://93.184.216.34:443/x"
    assert target.host_header == "example.com:443"


def test_pinning_brackets_an_ipv6_address() -> None:
    target = pin_target("https://example.com/x", "2606:2800:220:1:248:1893:25c8:1946")

    assert target.connect_url.startswith("https://[2606:")


def test_pinning_keeps_the_hostname_for_certificate_validation() -> None:
    """Connecting by address without this would fail, or worse be silenced by disabling checks."""
    assert pin_target("https://example.com/", "1.2.3.4").sni_hostname == "example.com"


def test_a_fetch_returns_the_body(monkeypatch) -> None:
    _public(monkeypatch)
    client = _client(
        lambda r: httpx.Response(
            200, text="hello", headers={"content-type": "text/plain"}
        )
    )

    result = safe_fetch_text("https://example.com/", client=client)

    assert isinstance(result, FetchResult)
    assert result.content == "hello"
    assert result.content_type == "text/plain"


def test_the_request_carries_the_original_host_not_the_address(monkeypatch) -> None:
    _public(monkeypatch)
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.headers.get("host", "")
        seen["url"] = str(request.url)
        return httpx.Response(200, text="ok")

    safe_fetch_text("https://example.com/p", client=_client(handler))

    assert seen["host"] == "example.com"
    assert "93.184.216.34" in seen["url"]


def test_a_redirect_to_an_internal_address_is_refused(monkeypatch) -> None:
    """A permitted first hop redirecting inward is the same attack with one more step."""

    def _resolve(host: str):
        return [
            ipaddress.ip_address(
                "93.184.216.34" if host == "example.com" else "10.0.0.5"
            )
        ]

    monkeypatch.setattr(netsec, "resolve", _resolve)
    client = _client(
        lambda r: httpx.Response(302, headers={"location": "https://internal.test/"})
    )

    with pytest.raises(netsec.URLSafetyError, match="disallowed address"):
        safe_fetch_text("https://example.com/", client=client)


def test_a_redirect_loop_stops_at_the_hop_limit(monkeypatch) -> None:
    _public(monkeypatch)
    client = _client(
        lambda r: httpx.Response(302, headers={"location": "https://example.com/n"})
    )

    with pytest.raises(netsec.URLSafetyError, match="redirects"):
        safe_fetch_text("https://example.com/", max_redirects=2, client=client)


def test_a_redirect_without_a_location_is_refused(monkeypatch) -> None:
    _public(monkeypatch)

    with pytest.raises(netsec.URLSafetyError, match="location"):
        safe_fetch_text(
            "https://example.com/", client=_client(lambda r: httpx.Response(302))
        )


def test_the_body_is_capped(monkeypatch) -> None:
    """An unbounded read is a memory exhaustion the caller never asked for."""
    _public(monkeypatch)
    client = _client(lambda r: httpx.Response(200, text="x" * 5000))

    result = safe_fetch_text("https://example.com/", max_bytes=100, client=client)

    assert len(result.content) == 100


def test_an_unsafe_url_is_refused_before_anything_is_opened() -> None:
    """Validation comes first, so a refused URL never reaches the network layer."""

    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(
            "a request was made for a URL that should have been refused"
        )

    with pytest.raises(netsec.URLSafetyError):
        safe_fetch_text("http://127.0.0.1/", client=_client(explode))


def test_a_non_success_response_raises(monkeypatch) -> None:
    _public(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        safe_fetch_text(
            "https://example.com/", client=_client(lambda r: httpx.Response(404))
        )
