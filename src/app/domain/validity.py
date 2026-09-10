"""Comparison validity — is this contrast sound enough to report?

Experiment trackers store, version and visualise runs. None of them adjudicate whether a
comparison between two arms is valid. This module does that one thing.

The defect it detects has a name in the missing-data literature: missingness that is **MNAR
with respect to the treatment arm**. A cell can leave the denominator through many channels —
it timed out, its container died, its verdict was never produced, its trace was incomplete. If
the *rate* of any such channel differs across arms, the exclusion does not cancel in a
contrast; it biases it, and it biases it in the direction the hypothesis predicts, because
weaker arms tend to fail in every way at once.

Two rules learned by getting this wrong:

1. **A check that cannot fail is worse than no check**, because it gets cited. An earlier
   implementation of this idea keyed its per-arm rate dictionary off a leftover loop variable,
   so it always held exactly one entry, always reported a spread of 1.0, and reported "clean"
   for weeks. Every function here therefore reports how much it examined, and the test suite
   contains a positive control that must fail.

2. **Pairing fixes contrasts, not absolute numbers.** Restricting to items every arm scored
   removes the bias from a delta. It does not give you a benchmark score, because that
   intersection selects for items every arm could finish, which is to say for tractability.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Protocol


class Observation(Protocol):
    """The minimum an object needs to be checked for comparison validity."""

    item: str
    """What was attempted — a task, an instance, a question. Pairing key."""

    arm: str
    """Which condition it was attempted under. The treatment variable."""

    channel: str
    """How this observation left the denominator, or `INCLUDED` if it did not."""


INCLUDED = "included"
"""Reserved channel name for an observation that counts toward its arm's denominator."""


@dataclass(frozen=True)
class ChannelSpread:
    """One exclusion channel, and how unevenly it fell across arms."""

    channel: str
    rate_by_arm: dict[str, float]
    lowest_arm: str
    highest_arm: str
    ratio: float
    """highest rate divided by lowest. `inf` when the lowest arm is zero and the highest is not."""

    absolute_difference: float

    def describe(self) -> str:
        lo, hi = self.rate_by_arm[self.lowest_arm], self.rate_by_arm[self.highest_arm]
        return (
            f"{self.channel}: {hi:.1%} ({self.highest_arm}) vs {lo:.1%} ({self.lowest_arm})"
        )


@dataclass(frozen=True)
class ValidityReport:
    """The verdict, plus enough context that a clean result is legible as a real result."""

    arms_examined: int
    channels_examined: int
    observations_examined: int
    flagged: list[ChannelSpread] = field(default_factory=list)
    paired_items: int = 0
    total_items: int = 0

    @property
    def sound(self) -> bool:
        """True when no exclusion channel differs across arms beyond the threshold."""
        return not self.flagged

    @property
    def could_have_flagged(self) -> bool:
        """False when the input could not have produced a finding either way.

        A report over fewer than two arms, or with no exclusion channels present at all, is
        not evidence of soundness. Read this before believing `sound`.
        """
        return self.arms_examined >= 2 and self.channels_examined >= 1

    def summary(self) -> str:
        if not self.could_have_flagged:
            return (
                f"inconclusive: {self.arms_examined} arm(s), {self.channels_examined} exclusion "
                f"channel(s) — this input cannot produce a finding"
            )
        if self.sound:
            return (
                f"sound: {self.channels_examined} channel(s) across {self.arms_examined} arms, "
                f"none differing beyond threshold"
            )
        return "not sound: " + "; ".join(c.describe() for c in self.flagged)


def missingness_by_arm(
    observations: Iterable[Observation],
) -> dict[str, dict[str, int]]:
    """Count observations per arm per channel, including the `INCLUDED` channel.

    Returns `{arm: {channel: count}}`. Arms with no observations do not appear; that is
    itself worth noticing, so callers should compare against the arms they expected.
    """
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for obs in observations:
        counts[obs.arm][obs.channel] += 1
    return {arm: dict(channels) for arm, channels in counts.items()}


def paired_items(observations: Iterable[Observation]) -> set[str]:
    """Items that every arm produced an INCLUDED observation for.

    This is the correct denominator for a contrast and the wrong one for a score.
    """
    by_arm: dict[str, set[str]] = defaultdict(set)
    all_arms: set[str] = set()
    for obs in observations:
        all_arms.add(obs.arm)
        if obs.channel == INCLUDED:
            by_arm[obs.arm].add(obs.item)
    if not all_arms or len(by_arm) < len(all_arms):
        return set()
    return set.intersection(*by_arm.values())


def check_comparison(
    observations: Iterable[Observation],
    *,
    spread_ratio_threshold: float = 2.0,
    minimum_absolute_difference: float = 0.02,
) -> ValidityReport:
    """Adjudicate whether a contrast across arms is sound enough to report.

    A channel is flagged when its rate differs across arms by more than
    `spread_ratio_threshold` **and** by at least `minimum_absolute_difference` in absolute
    terms. The second condition exists because a ratio between two tiny rates is unstable and
    would otherwise flag noise; the first exists because an absolute difference between two
    large rates may be unremarkable.

    The report always states how many arms, channels and observations were examined, so that a
    clean verdict from an input that could not have produced a finding is visible as such.
    """
    observations = list(observations)
    counts = missingness_by_arm(observations)
    arms = sorted(counts)
    totals = {arm: sum(channels.values()) for arm, channels in counts.items()}
    channels = sorted(
        {ch for channels_ in counts.values() for ch in channels_ if ch != INCLUDED}
    )

    flagged: list[ChannelSpread] = []
    if len(arms) >= 2:
        for channel in channels:
            rates = {
                arm: (counts[arm].get(channel, 0) / totals[arm]) if totals[arm] else 0.0
                for arm in arms
            }
            lowest = min(rates, key=lambda a: rates[a])
            highest = max(rates, key=lambda a: rates[a])
            lo, hi = rates[lowest], rates[highest]
            if hi - lo < minimum_absolute_difference:
                continue
            ratio = float("inf") if lo == 0 else hi / lo
            if ratio > spread_ratio_threshold:
                flagged.append(
                    ChannelSpread(
                        channel=channel,
                        rate_by_arm=rates,
                        lowest_arm=lowest,
                        highest_arm=highest,
                        ratio=ratio,
                        absolute_difference=hi - lo,
                    )
                )

    return ValidityReport(
        arms_examined=len(arms),
        channels_examined=len(channels),
        observations_examined=len(observations),
        flagged=flagged,
        paired_items=len(paired_items(observations)),
        total_items=len({obs.item for obs in observations}),
    )
