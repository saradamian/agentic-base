"""Who may read and write which tenant's runs, and which scorers a writer may speak for.

A run record holds transcripts, the people runs acted for and the class of data they touched, so
the service refuses by default. ``AUTH=tokens``, the default, requires a bearer token on every
data route and grants it the tenants ``API_TOKENS`` lists for it; ``"*"`` grants every tenant, for
an operator. With no tokens configured, every data route refuses and says what to set, rather than
serving the corpus to whoever reaches it. ``AUTH=none`` turns the check off, for local development
only.

A citable outcome needs more than a writer token. An entry in ``API_TOKENS`` may map to an object
``{"tenants": [...], "label_sources": [...]}`` instead of a plain tenant list, and only the
citable sources named there may be asserted through that token; the plain list shape grants none,
so an agent's own writer token records diagnostic outcomes and cannot mint results in the
harness's or a person's name.

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
from agentic_base.domain.outcomes import (
    CITABLE_LABEL_SOURCES,
    LabelAuthority,
    LabelSource,
    authority_of,
)

ALL_TENANTS = "*"

_bearer = HTTPBearer(auto_error=False, description="A token listed in API_TOKENS.")


@dataclass(frozen=True)
class Grant:
    """What one token is trusted with. ``tenants`` is None for every tenant; ``label_sources``
    holds the citable scorers this token may assert, empty unless the deployment named them."""

    tenants: frozenset[str] | None
    label_sources: frozenset[LabelSource] = frozenset()


@dataclass(frozen=True)
class Access:
    """What one caller may touch. ``tenants`` is None for every tenant; ``label_sources`` is
    None when the check is off entirely (``AUTH=none``)."""

    tenants: frozenset[str] | None
    label_sources: frozenset[LabelSource] | None = frozenset()

    def allows(self, tenant: str) -> bool:
        return self.tenants is None or tenant in self.tenants

    def require(self, tenant: str) -> None:
        """Refuse a request that names a tenant this caller may not use."""
        if not self.allows(tenant):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this token may not use tenant {tenant!r}",
            )

    def require_label_source(self, source: LabelSource) -> None:
        """Refuse a citable outcome from a token not granted its scorer.

        Diagnostic sources pass without a grant: the grant guards what may be cited, not what
        may be observed.
        """
        if authority_of(source) is not LabelAuthority.AUTHORITATIVE:
            return
        if self.label_sources is None or source in self.label_sources:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"this token may not assert label_source {source.value!r}: its API_TOKENS "
                f"entry does not name {source.value!r} under label_sources"
            ),
        )


@dataclass(frozen=True)
class AccessPolicy:
    """The configured tokens, or no check at all."""

    enabled: bool
    tokens: dict[str, Grant]

    def resolve(self, token: str | None) -> Access:
        if not self.enabled:
            return Access(tenants=None, label_sources=None)
        if not self.tokens:
            raise _unauthorised(
                "no API tokens are configured: set API_TOKENS, or AUTH=none for local development"
            )
        if not token:
            raise _unauthorised("a bearer token is required")
        granted = Grant(tenants=frozenset())
        found = False
        for known, grant in self.tokens.items():
            # Compare against every token, so the time taken does not say how close a guess was.
            if hmac.compare_digest(known.encode(), token.encode()):
                granted, found = grant, True
        if not found:
            raise _unauthorised("the bearer token is not recognised")
        return Access(tenants=granted.tenants, label_sources=granted.label_sources)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def parse_tokens(raw: str) -> dict[str, Grant]:
    """``{"token": ["tenant", ...]}`` or ``{"token": {"tenants": [...], "label_sources":
    [...]}}`` into grants. The list shape grants no label sources, so a token configured before
    the grant existed keeps working for diagnostic outcomes and nothing more. Refuses a
    malformed value at start."""
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
    grants: dict[str, Grant] = {}
    for token, spec in loaded.items():
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError(
                "every API token must be a string of at least 16 characters"
            )
        if isinstance(spec, dict):
            unknown = sorted(set(spec) - {"tenants", "label_sources"})
            if unknown:
                raise ValueError(
                    "an API token grant knows 'tenants' and 'label_sources', "
                    f"not {', '.join(unknown)}"
                )
            tenants = spec.get("tenants", [])
            sources = spec.get("label_sources", [])
        else:
            tenants, sources = spec, []
        if not isinstance(tenants, list) or not all(
            isinstance(t, str) for t in tenants
        ):
            raise ValueError("every API token must map to a list of tenant names")
        if not isinstance(sources, list) or not all(
            isinstance(s, str) for s in sources
        ):
            raise ValueError("label_sources must be a list of label source names")
        grants[token] = Grant(
            tenants=None if ALL_TENANTS in tenants else frozenset(tenants),
            label_sources=frozenset(_citable_source(s) for s in sources),
        )
    return grants


def _citable_source(name: str) -> LabelSource:
    """A grantable label source, by name. Only citable sources can be granted: a diagnostic
    outcome needs no grant, so granting one would read as if it did something."""
    try:
        source = LabelSource(name)
    except ValueError:
        raise ValueError(
            f"label_sources names no known source: {name!r}. The citable sources are "
            f"{', '.join(sorted(s.value for s in CITABLE_LABEL_SOURCES))}"
        ) from None
    if source not in CITABLE_LABEL_SOURCES:
        raise ValueError(
            f"label_sources may only grant citable sources, and {name!r} is not one: "
            "a diagnostic outcome needs no grant"
        )
    return source


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
