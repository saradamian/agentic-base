"""Comparison validity — is this contrast sound enough to report?

Experiment trackers store, version and visualise runs. None of them adjudicate whether a
comparison between two arms is valid. This module does that one thing, and it is not a new
thing: clinical trials have required it for two decades as the CONSORT flow diagram, a per-arm
accounting of who was assessed, who was excluded and why, and who was analysed. The vocabulary
here is deliberately CONSORT's, so a reader from that world recognises the artifact. The
intention-to-treat population is every observation an arm attempted; the per-protocol
population is `paired_items`, and CONSORT's caution about the second is the second rule below.

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

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from agentic_base.limits import get_limits


class Observation(Protocol):
    """The minimum an object needs to be checked for comparison validity."""

    @property
    def item(self) -> str:
        """What was attempted — a task, an instance, a question. Pairing key."""

    @property
    def arm(self) -> str:
        """Which condition it was attempted under. The treatment variable."""

    @property
    def channel(self) -> str:
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
        return f"{self.channel}: {hi:.1%} ({self.highest_arm}) vs {lo:.1%} ({self.lowest_arm})"


@dataclass(frozen=True)
class ArmFlow:
    """One arm's row of a CONSORT-style flow diagram.

    `assessed` is every observation the arm attempted. `excluded` maps each exclusion channel
    to how many left through it. `analysed` is what remains, and the three always reconcile:
    `assessed == analysed + sum(excluded.values())`. This is the artifact the standard makes
    mandatory, and it is what turns a verdict into something a reader can check.
    """

    arm: str
    assessed: int
    excluded: dict[str, int]
    analysed: int

    def describe(self) -> str:
        reasons = (
            ", ".join(f"{n} {ch}" for ch, n in sorted(self.excluded.items())) or "none"
        )
        left = self.assessed - self.analysed
        return f"{self.arm}: assessed {self.assessed}; excluded {left} ({reasons}); analysed {self.analysed}"


@dataclass(frozen=True)
class ValidityReport:
    """The verdict, plus enough context that a clean result is legible as a real result."""

    arms_examined: int
    channels_examined: int
    observations_examined: int
    flagged: list[ChannelSpread] = field(default_factory=list)
    paired_items: int = 0
    total_items: int = 0
    flow: dict[str, ArmFlow] = field(default_factory=dict)
    """The per-arm accounting the verdict rests on. Present even when the verdict is sound."""

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


def flow_by_arm(observations: Iterable[Observation]) -> dict[str, ArmFlow]:
    """The CONSORT flow: per arm, how many were assessed, how many left and why, how many remain.

    A pure re-labelling of `missingness_by_arm` into the standard's vocabulary, kept as its own
    function because the vocabulary is the point: a reader who knows the flow diagram should
    not have to learn ours.
    """
    flow: dict[str, ArmFlow] = {}
    for arm, channels in missingness_by_arm(observations).items():
        analysed = channels.get(INCLUDED, 0)
        excluded = {ch: n for ch, n in channels.items() if ch != INCLUDED}
        flow[arm] = ArmFlow(
            arm=arm,
            assessed=analysed + sum(excluded.values()),
            excluded=excluded,
            analysed=analysed,
        )
    return flow


def render_flow(flow: dict[str, ArmFlow]) -> str:
    """One line per arm, in the order a reader would scan them."""
    return "\n".join(flow[arm].describe() for arm in sorted(flow))


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
    spread_ratio_threshold: float | None = None,
    minimum_absolute_difference: float | None = None,
) -> ValidityReport:
    """Adjudicate whether a contrast across arms is sound enough to report.

    A channel is flagged when its rate differs across arms by more than
    `spread_ratio_threshold` **and** by at least `minimum_absolute_difference` in absolute
    terms. The second condition exists because a ratio between two tiny rates is unstable and
    would otherwise flag noise; the first exists because an absolute difference between two
    large rates may be unremarkable.

    The report always states how many arms, channels and observations were examined, so that a
    clean verdict from an input that could not have produced a finding is visible as such.

    A threshold left out is read from the limits (`AP_VALIDITY_SPREAD_RATIO`,
    `AP_VALIDITY_MIN_ABSOLUTE_DIFFERENCE`), so a deployment tunes it in one place for every
    surface that asks.
    """
    limits = get_limits()
    if spread_ratio_threshold is None:
        spread_ratio_threshold = limits.validity_spread_ratio
    if minimum_absolute_difference is None:
        minimum_absolute_difference = limits.validity_min_absolute_difference
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
        flow=flow_by_arm(observations),
    )


def report_as_dict(report: ValidityReport) -> dict[str, Any]:
    """The report as plain JSON values, the one shape every surface serves.

    An infinite ratio, a channel absent from one arm, becomes ``None``, because JSON has no
    infinity and a serialiser that writes one produces a document other readers reject.
    """
    return {
        "sound": report.sound,
        "could_have_flagged": report.could_have_flagged,
        "summary": report.summary(),
        "arms_examined": report.arms_examined,
        "channels_examined": report.channels_examined,
        "observations_examined": report.observations_examined,
        "paired_items": report.paired_items,
        "total_items": report.total_items,
        "flagged": [
            {
                "channel": c.channel,
                "rate_by_arm": c.rate_by_arm,
                "lowest_arm": c.lowest_arm,
                "highest_arm": c.highest_arm,
                "ratio": None if math.isinf(c.ratio) else c.ratio,
                "absolute_difference": c.absolute_difference,
                "description": c.describe(),
            }
            for c in report.flagged
        ],
        "flow": [
            {
                "arm": f.arm,
                "assessed": f.assessed,
                "excluded": f.excluded,
                "analysed": f.analysed,
                "description": f.describe(),
            }
            for f in (report.flow[arm] for arm in sorted(report.flow))
        ],
    }
