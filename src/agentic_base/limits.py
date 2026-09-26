"""Every limit in one place, resolved when it is read.

Two things this file is trying to avoid.

Numbers buried in the code that uses them cannot be tuned per deployment, cannot be found when a
value turns out to be wrong, and stop being visible in review.

Constants resolved at import time silently ignore anything layered afterwards. We hit that in the
predecessor project: environment values for every limit were ignored unless some other module
happened to import the configuration first. On a platform where configuration arrives as mounted
files and injected variables, that failure is harder to see, not easier. So limits are a settings
object read through a cached accessor, and the cache can be cleared.
"""

from __future__ import annotations

from functools import cache

from pydantic_settings import BaseSettings


class Limits(BaseSettings):
    """Caps and thresholds. Every field is settable from the environment with the AP_ prefix."""

    model_config = {"env_prefix": "AP_"}

    transcript_max_messages: int = 2000
    """Messages kept in one run record. A longer transcript is stored truncated and the loss is
    recorded, never dropped quietly."""

    tool_output_max_chars: int = 30_000
    """What one tool result may contribute to a transcript. This is a capability limit as much as
    a storage one: raising it changes what the model can see, so two runs at different values are
    not comparable."""

    fetch_max_bytes: int = 2_000_000
    fetch_timeout_s: int = 15
    fetch_max_redirects: int = 5

    llm_probe_timeout_s: int = 10
    """Budget for the pre-flight completion probe."""

    validity_spread_ratio: float = 2.0
    """Deprecated: the old decision rule's ratio threshold. The verdict is decided by the
    interval since the rewrite (`check_comparison` says why); the ratio is reported as a
    diagnostic only. Kept so a deployment that sets `AP_VALIDITY_SPREAD_RATIO` keeps parsing."""

    validity_min_absolute_difference: float = 0.02
    """Floor below which a rate difference across arms is unremarkable, however certain the
    interval is that it is real."""

    validity_interval_max_width: float = 0.20
    """When the 95% interval on a rate difference spans zero but is wider than this, the
    verdict is "inconclusive: too little data" rather than "sound" — an interval that wide
    could not have told a real gap from none."""

    mcp_max_rows: int = 200
    """Rows one MCP call may return. A chat client pays for each of them in context."""

    mcp_max_transcript_chars: int = 60_000
    """The most transcript, in characters of messages, one MCP call returns; ``0`` for no cap. A
    caller may ask for less, and pages through a longer transcript with ``from_message``, so the
    cap bounds one reply without hiding any part of a run."""


@cache
def get_limits() -> Limits:
    """The active limits. Call `get_limits.cache_clear()` after changing the environment."""
    return Limits()
