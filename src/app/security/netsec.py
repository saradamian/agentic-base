"""Outbound request safety.

An agent that fetches a URL on behalf of a user is a server-side request forgery primitive
unless something checks the target first. Inside a cluster the blast radius includes the
scheduler API, cloud metadata endpoints and every internal service on the network.

Checks applied, in order: the scheme, credentials smuggled into the authority, the port, and
then the addresses the host resolves to. Resolution matters because a public name can point at
a private address, which is the usual way these checks are bypassed.

Callers that fetch should also pin the address they validated, otherwise the name can resolve
differently between the check and the connection.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

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
    safe, reason = is_url_safe(url, allowed_ports=allowed_ports, resolve_dns=resolve_dns)
    if not safe:
        raise URLSafetyError(reason)
