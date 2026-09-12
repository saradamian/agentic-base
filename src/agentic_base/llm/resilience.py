"""Retrying against a self-hosted endpoint that restarts under you.

The failure this exists for is specific and takes a long time to find. When a serving backend
restarts, pooled keep-alive connections are not reset, they are simply never answered again.
Every retry that reuses the pool then hangs until its timeout, so a client never recovers in
process even after the backend is healthy. In the predecessor project this was watched across
roughly fifteen backend drops before the cause was understood.

Three things together fix it, and all three are needed:

1. An explicit request timeout, so a stalled call raises instead of hanging.
2. Retries owned by one layer. An SDK's own retry loop silently reuses the same dead pool, so it
   is turned off rather than layered with.
3. A fresh transport on connection failure, before the retry is attempted.

The retry predicate is deliberately narrow. A 502, 503 or 504 is a proxy or a backend that is
restarting, and retrying is right. A 500 is a bug in the request and retrying it just costs
money twice.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
"""Rate limiting, and the three gateway statuses a restarting backend produces."""

NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 422, 500})
"""A request-level fault. Retrying reproduces it."""


def should_retry_status(status_code: int) -> bool:
    """Whether an HTTP status is worth another attempt."""
    return status_code in RETRYABLE_STATUS


def should_retry_exception(exc: BaseException) -> bool:
    """Whether a transport-level failure is worth another attempt.

    Timeouts and connection errors qualify, and both are the dead-pool signature.
    """
    return isinstance(
        exc, httpx.TimeoutException | httpx.ConnectError | httpx.ReadError
    )


def is_wrapped_timeout(message: str) -> bool:
    """Whether a 400 is really a timeout wrapped by a gateway.

    At least one gateway in front of our own models returns an internal read timeout as a 400
    with the original exception name in the body. Treating that as a request fault means never
    retrying a transient failure.
    """
    return "readtimeout" in message.lower().replace(" ", "")


class TransportPool:
    """Holds a client and can throw it away.

    Recreating the client is the part that matters. Without it a retry reuses connections that
    will never answer, and the retry budget is spent waiting.
    """

    def __init__(self, factory: Callable[[], httpx.Client]) -> None:
        self._factory = factory
        self._client: httpx.Client | None = None
        self.recycles = 0

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = self._factory()
        return self._client

    def recycle(self) -> None:
        """Discard the current client so the next call opens fresh connections."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self.recycles += 1

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
