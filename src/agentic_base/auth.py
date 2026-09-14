"""Who may read and write which tenant's runs.

A run record holds transcripts, the people runs acted for and the class of data they touched, so
the service refuses by default. ``AUTH=tokens``, the default, requires a bearer token on every
data route and grants it the tenants ``API_TOKENS`` lists for it; ``"*"`` grants every tenant, for
an operator. With no tokens configured, every data route refuses and says what to set, rather than
serving the corpus to whoever reaches it. ``AUTH=none`` turns the check off, for local development
only.

A token that may not see a tenant is told 403 when it names that tenant, and 404 when it asks for
one of that tenant's runs by id, so the answer does not confirm that a run exists. Tokens are
compared in constant time and never logged.

This is the service's own floor, not the platform's identity: on the Developer Platform the
gateway authenticates people through the federation, and these tokens identify the callers that
write runs, one per writer.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from functools import cache
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette import status

from agentic_base.config import get_settings

ALL_TENANTS = "*"

_bearer = HTTPBearer(auto_error=False, description="A token listed in API_TOKENS.")


@dataclass(frozen=True)
class Access:
    """What one caller may touch. ``tenants`` is None for every tenant."""

    tenants: frozenset[str] | None

    def allows(self, tenant: str) -> bool:
        return self.tenants is None or tenant in self.tenants

    def require(self, tenant: str) -> None:
        """Refuse a request that names a tenant this caller may not use."""
        if not self.allows(tenant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this token may not use tenant {tenant!r}",
            )


@dataclass(frozen=True)
class AccessPolicy:
    """The configured tokens, or no check at all."""

    enabled: bool
    tokens: dict[str, frozenset[str] | None]

    def resolve(self, token: str | None) -> Access:
        if not self.enabled:
            return Access(tenants=None)
        if not self.tokens:
            raise _unauthorised(
                "no API tokens are configured: set API_TOKENS, or AUTH=none for local development"
            )
        if not token:
            raise _unauthorised("a bearer token is required")
        granted: frozenset[str] | None = frozenset()
        found = False
        for known, tenants in self.tokens.items():
            # Compare against every token, so the time taken does not say how close a guess was.
            if hmac.compare_digest(known.encode(), token.encode()):
                granted, found = tenants, True
        if not found:
            raise _unauthorised("the bearer token is not recognised")
        return Access(tenants=granted)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def parse_tokens(raw: str) -> dict[str, frozenset[str] | None]:
    """``{"token": ["tenant", ...]}`` into grants. Refuses a malformed value at start."""
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"API_TOKENS is not valid JSON: {exc.msg}") from None
    if not isinstance(loaded, dict):
        raise ValueError(
            "API_TOKENS must be a JSON object of token to a list of tenants"
        )
    grants: dict[str, frozenset[str] | None] = {}
    for token, tenants in loaded.items():
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError(
                "every API token must be a string of at least 16 characters"
            )
        if not isinstance(tenants, list) or not all(
            isinstance(t, str) for t in tenants
        ):
            raise ValueError("every API token must map to a list of tenant names")
        grants[token] = None if ALL_TENANTS in tenants else frozenset(tenants)
    return grants


@cache
def get_access_policy() -> AccessPolicy:
    """The policy from the settings, built once. A wrong ``AUTH`` value fails the start."""
    settings = get_settings()
    mode = settings.auth.strip().lower()
    if mode not in {"tokens", "none"}:
        raise ValueError(f"AUTH must be 'tokens' or 'none', not {settings.auth!r}")
    return AccessPolicy(
        enabled=mode == "tokens",
        tokens=parse_tokens(settings.api_tokens.get_secret_value()),
    )


def caller_access(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    policy: Annotated[AccessPolicy, Depends(get_access_policy)],
) -> Access:
    """FastAPI dependency: what the calling token may touch."""
    return policy.resolve(credentials.credentials if credentials else None)
