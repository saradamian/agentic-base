"""Outbound request safety.

An agent that fetches a URL on behalf of a user is a server-side request forgery primitive
unless something checks the target first. Inside a cluster the blast radius includes the
scheduler API, cloud metadata endpoints and every internal service on the network.

Checks applied, in order: the scheme, credentials smuggled into the authority, the port, and
then the addresses the host resolves to. Resolution matters because a public name can point at
a private address, which is the usual way these checks are bypassed.

Validating and then fetching separately is not enough on its own. Between the check and the
connection the name is resolved a second time, so a host can answer the first lookup with a public
address and the second with a private one. `safe_fetch_text` closes that by connecting to the
address that was actually approved, carrying the original hostname in the Host header and in the
TLS server name so certificate validation still targets the real host.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.limits import get_limits

ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_ALLOWED_PORTS = frozenset({80, 443})

IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class URLSafetyError(Exception):
    """A URL failed validation and must not be fetched."""


def is_disallowed_ip(ip: IpAddress) -> bool:
    """Addresses no outbound agent request may reach."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve(hostname: str) -> list[IpAddress]:
    """Every distinct address a hostname resolves to, or an empty list if it does not resolve."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    seen: set[str] = set()
    out: list[IpAddress] = []
    for *_, sockaddr in infos:
        raw = str(sockaddr[0])
        if raw in seen:
            continue
        seen.add(raw)
        try:
            out.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    return out


def is_url_safe(
    url: str,
    *,
    allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    resolve_dns: bool = True,
) -> tuple[bool, str]:
    """Return whether the URL may be fetched, and why if it may not.

    Never raises. A failure to resolve is treated as unsafe, because a check that could not run
    must not report a pass.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False, "malformed URL"

    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"disallowed scheme: {parsed.scheme!r}"
    if parsed.username or parsed.password:
        return False, "credentials in the URL authority are not allowed"

    host = (parsed.hostname or "").lower().strip("[]")
    if not host:
        return False, "empty hostname"

    try:
        port = parsed.port
    except ValueError:
        return False, "malformed port"
    if port is not None and port not in allowed_ports:
        return False, f"port {port} not allowed"

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_disallowed_ip(literal):
            return False, f"disallowed address: {literal}"
        return True, "ok"

    if not resolve_dns:
        return True, "ok"

    addresses = resolve(host)
    if not addresses:
        return False, f"could not resolve {host!r}"
    for ip in addresses:
        if is_disallowed_ip(ip):
            return False, f"{host!r} resolves to a disallowed address: {ip}"
    return True, "ok"


def validate_url(
    url: str,
    *,
    allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    resolve_dns: bool = True,
) -> None:
    """Raise URLSafetyError if the URL must not be fetched."""
    safe, reason = is_url_safe(
        url, allowed_ports=allowed_ports, resolve_dns=resolve_dns
    )
    if not safe:
        raise URLSafetyError(reason)


# --- fetching -----------------------------------------------------------------------------


@dataclass(frozen=True)
class PinnedTarget:
    """Where to connect, and how to keep the request addressed to the original host."""

    connect_url: str
    host_header: str
    sni_hostname: str


@dataclass(frozen=True)
class FetchResult:
    url: str
    """The final URL after any redirects."""

    content_type: str
    content: str


def pin_target(url: str, address: str) -> PinnedTarget:
    """Rewrite a URL to connect to a specific address while still addressing the original host.

    The hostname is preserved in the Host header and as the TLS server name, so certificate
    validation is unaffected. This is what makes the fetch reach the address that was checked
    rather than whatever the name resolves to a second time.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().strip("[]")
    port = f":{parsed.port}" if parsed.port else ""
    literal = f"[{address}]" if ":" in address else address
    rest = parsed.path or "/"
    if parsed.query:
        rest = f"{rest}?{parsed.query}"
    return PinnedTarget(
        connect_url=f"{parsed.scheme}://{literal}{port}{rest}",
        host_header=f"{host}{port}",
        sni_hostname=host,
    )


def safe_fetch_text(
    url: str,
    *,
    timeout_s: int | None = None,
    max_bytes: int | None = None,
    max_redirects: int | None = None,
    allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    headers: dict[str, str] | None = None,
    client: Any = None,
) -> FetchResult:
    """Fetch a URL with the address pinned to the one that was validated.

    Every redirect target is validated and pinned in turn, because a permitted first hop that
    redirects to an internal address is the same attack with one more step.

    Raises `URLSafetyError` when any hop fails validation, and `httpx.HTTPStatusError` on a
    non-success response.

    `client` exists so a caller can supply a transport. Nothing is opened before the first URL has
    been validated, so a refused URL never reaches the network layer at all.
    """
    import httpx

    limits = get_limits()
    timeout = timeout_s if timeout_s is not None else limits.fetch_timeout_s
    cap = max_bytes if max_bytes is not None else limits.fetch_max_bytes
    hops = max_redirects if max_redirects is not None else limits.fetch_max_redirects

    validate_url(url, allowed_ports=allowed_ports)

    owned = client is None
    if owned:
        client = httpx.Client(follow_redirects=False, timeout=timeout)
    current = url
    try:
        for _ in range(hops + 1):
            validate_url(current, allowed_ports=allowed_ports)
            addresses = [
                ip for ip in resolve(_hostname(current)) if not is_disallowed_ip(ip)
            ]
            if addresses:
                target = pin_target(current, str(addresses[0]))
                request_url = target.connect_url
                request_headers = {**(headers or {}), "Host": target.host_header}
                extensions = {"sni_hostname": target.sni_hostname}
            else:
                # An address literal: validate_url already checked it, nothing to pin.
                request_url, request_headers, extensions = (
                    current,
                    dict(headers or {}),
                    {},
                )

            response = client.get(
                request_url, headers=request_headers, extensions=extensions
            )
            if response.is_redirect:
                location = response.headers.get("location", "")
                if not location:
                    raise URLSafetyError("redirect without a location")
                current = str(httpx.URL(current).join(location))
                continue

            response.raise_for_status()
            body = response.content[:cap]
            return FetchResult(
                url=current,
                content_type=response.headers.get("content-type", ""),
                content=body.decode(response.encoding or "utf-8", errors="replace"),
            )

    finally:
        if owned:
            client.close()

    raise URLSafetyError(f"more than {hops} redirects")


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().strip("[]")
