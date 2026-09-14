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
    """How much an exclusion rate may differ across arms before a contrast is called unsound."""

    validity_min_absolute_difference: float = 0.02
    """Floor below which a ratio between two small rates is treated as noise."""

    mcp_max_rows: int = 200
    """Rows one MCP call may return. A chat client pays for each of them in context."""

    mcp_max_transcript_chars: int = 60_000
    """How much of one run's transcript an MCP call returns. Past it, messages are left out and
    the result says how many, so a long run is legible as long rather than as short."""


@cache
def get_limits() -> Limits:
    """The active limits. Call `get_limits.cache_clear()` after changing the environment."""
    return Limits()
