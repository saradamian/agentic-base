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

The decision is made three ways at once, because each closes a hole the others leave open:

- **Per channel and pooled.** Channel names are free text from the recording path, so twelve
  per cent of an arm lost across twelve differently-worded timeouts is under two per cent in
  every row of the table. The per-channel table stays, as the diagnostic a reader checks, but
  the verdict also tests the pooled left-the-denominator-for-any-reason rate per arm, which no
  choice of channel names can dilute.
- **Absence is an exclusion.** When the arms share an item vocabulary, an item one arm
  attempted and another has no observation for left that arm's denominator as surely as a
  timeout did, and is counted as the reserved channel `never_attempted`. When the arms share
  no items the report says so instead of silently comparing different task sets.
- **An interval, not a ratio.** A channel is flagged only when the Newcombe (1998) score
  interval on its rate difference excludes zero *and* the observed difference clears an
  absolute floor. When the interval spans zero but is wider than a stated width, the verdict
  is "inconclusive: too little data" rather than "sound" — one timeout in five runs is not a
  finding, and neither is its absence.

Two rules learned by getting this wrong:

1. **A check that cannot fail is worse than no check**, because it gets cited. An earlier
   implementation of this idea keyed its per-arm rate dictionary off a leftover loop variable,
   so it always held exactly one entry, always reported a spread of 1.0, and reported "clean"
   for weeks. Every function here therefore reports how much it examined, and the test suite
   contains a positive control that must fail. The successor to that rule — flag only when the
   rates' ratio and their difference both clear thresholds — could itself be driven to "sound"
   four ways (free-text channels, high base rates, unattempted items, and it flagged noise at
   tiny n); the decision above replaced it, and the tests pin each of those four inputs.

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

NEVER_ATTEMPTED = "never_attempted"
"""Reserved channel name for an item another arm attempted and this arm never did. Synthesised
by `check_comparison` when the arms share an item vocabulary; it never comes from a record."""

ANY_EXCLUSION = "any_exclusion"
"""Reserved channel name for the pooled rate: everything that left an arm's denominator, for
any reason. This is the rate free-text channel names cannot dilute."""

_Z_95 = 1.96
"""Two-sided 95% normal quantile, the confidence the intervals below are stated at."""


def wilson_interval(count: int, total: int, *, z: float = _Z_95) -> tuple[float, float]:
    """The Wilson (1927) score interval for a single proportion `count / total`.

    The closed-form roots of the score equation, clamped to [0, 1]. Chosen over the Wald
    interval because it behaves at the boundaries this module lives at: a zero count gives a
    non-degenerate interval instead of (0, 0).
    """
    if total <= 0:
        raise ValueError("an interval over zero observations is not an interval")
    p = count / total
    z2 = z * z
    denominator = 1 + z2 / total
    centre = (p + z2 / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def newcombe_interval(
    count_a: int, total_a: int, count_b: int, total_b: int, *, z: float = _Z_95
) -> tuple[float, float]:
    """Newcombe's score interval for the difference `count_a/total_a - count_b/total_b`.

    Method 10 of Newcombe (1998), "Interval estimation for the difference between independent
    proportions", Statistics in Medicine 17:873–890: take each proportion's Wilson interval
    (l, u) and combine the margins square-and-add around the observed difference d:

        lower = d - sqrt((p_a - l_a)^2 + (u_b - p_b)^2)
        upper = d + sqrt((u_a - p_a)^2 + (p_b - l_b)^2)

    Plain `math`, no distribution tables, so the library half keeps its dependency floor.
    """
    p_a, p_b = count_a / total_a, count_b / total_b
    lower_a, upper_a = wilson_interval(count_a, total_a, z=z)
    lower_b, upper_b = wilson_interval(count_b, total_b, z=z)
    difference = p_a - p_b
    return (
        difference - math.sqrt((p_a - lower_a) ** 2 + (upper_b - p_b) ** 2),
        difference + math.sqrt((upper_a - p_a) ** 2 + (p_b - lower_b) ** 2),
    )


@dataclass(frozen=True)
class ChannelSpread:
    """One exclusion channel, how unevenly it fell across arms, and the interval on that."""

    channel: str
    rate_by_arm: dict[str, float]
    lowest_arm: str
    highest_arm: str
    ratio: float
    """highest rate divided by lowest. `inf` when the lowest arm is zero and the highest is
    not. A diagnostic since the interval took over the decision; kept so a reader of an old
    report and a new one sees the same fields."""

    absolute_difference: float
    interval_low: float = 0.0
    interval_high: float = 0.0
    """95% Newcombe score interval on `absolute_difference`. The decision reads these: a flag
    needs `interval_low > 0`, and an interval that spans zero but is wider than the stated
    width is too little data to call either way."""

    def describe(self) -> str:
        lo, hi = self.rate_by_arm[self.lowest_arm], self.rate_by_arm[self.highest_arm]
        return (
            f"{self.channel}: {hi:.1%} ({self.highest_arm}) vs {lo:.1%} ({self.lowest_arm}),"
            f" 95% interval {self.interval_low * 100:+.1f} to {self.interval_high * 100:+.1f} pp"
        )


@dataclass(frozen=True)
class ArmFlow:
    """One arm's row of a CONSORT-style flow diagram.

    `assessed` is every observation the arm attempted, plus any shared-vocabulary item it never
    attempted (the `never_attempted` channel). `excluded` maps each exclusion channel to how
    many left through it. `analysed` is what remains, and the three always reconcile:
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

    inconclusive: list[ChannelSpread] = field(default_factory=list)
    """Channels whose interval spans zero but is wider than the stated width: there was too
    little data to tell a real gap from none. Not findings, and not evidence of soundness."""

    item_sets_comparable: bool = True
    """False when the arms share no item keys at all. Absence could then not be counted, and
    the arms may not even be attempting the same task set; the summary says so."""

    @property
    def sound(self) -> bool:
        """True when no exclusion channel, nor the pooled rate, differs across arms beyond
        what the interval and the absolute floor allow. Read `could_have_flagged` first."""
        return not self.flagged

    @property
    def could_have_flagged(self) -> bool:
        """False when the input could not have produced a finding either way.

        A report over fewer than two arms, or with no exclusion channels present at all, is
        not evidence of soundness — and neither is one whose every difference sat inside an
        interval too wide to call. Read this before believing `sound`.
        """
        if self.arms_examined < 2 or self.channels_examined < 1:
            return False
        return bool(self.flagged) or not self.inconclusive

    def summary(self) -> str:
        note = (
            ""
            if self.item_sets_comparable
            else "; the arms share no items, so what one arm never attempted was not counted"
        )
        if self.arms_examined < 2 or self.channels_examined < 1:
            return (
                f"inconclusive: {self.arms_examined} arm(s), {self.channels_examined} exclusion "
                f"channel(s) — this input cannot produce a finding" + note
            )
        if not self.sound:
            return "not sound: " + "; ".join(c.describe() for c in self.flagged) + note
        if self.inconclusive:
            return (
                "inconclusive: too little data — "
                + "; ".join(c.describe() for c in self.inconclusive)
                + note
            )
        return (
            f"sound: {self.channels_examined} channel(s) across {self.arms_examined} arms, "
            f"no difference the interval can tell from zero" + note
        )


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


def _flow_from_counts(counts: dict[str, dict[str, int]]) -> dict[str, ArmFlow]:
    """Re-label per-arm channel counts as CONSORT flow rows."""
    flow: dict[str, ArmFlow] = {}
    for arm, channels in counts.items():
        analysed = channels.get(INCLUDED, 0)
        excluded = {ch: n for ch, n in channels.items() if ch != INCLUDED}
        flow[arm] = ArmFlow(
            arm=arm,
            assessed=analysed + sum(excluded.values()),
            excluded=excluded,
            analysed=analysed,
        )
    return flow


def flow_by_arm(observations: Iterable[Observation]) -> dict[str, ArmFlow]:
    """The CONSORT flow: per arm, how many were assessed, how many left and why, how many remain.

    A pure re-labelling of `missingness_by_arm` into the standard's vocabulary, kept as its own
    function because the vocabulary is the point: a reader who knows the flow diagram should
    not have to learn ours. Counts only what was observed; the `never_attempted` synthesis
    happens in `check_comparison`, which knows every arm.
    """
    return _flow_from_counts(missingness_by_arm(observations))


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


def _count_absence(
    counts: dict[str, dict[str, int]], observations: list[Observation]
) -> bool:
    """Add each arm's never-attempted items to `counts`, in place.

    An item is never-attempted for an arm when some other arm has an observation for it and
    this arm has none. That only means something when the arms share an item vocabulary, taken
    here as: every arm has item keys, and at least one item was attempted by every arm.
    Returns whether they do; when they do not, `counts` is left alone and the report says so
    rather than silently comparing different task sets.
    """
    items_by_arm: dict[str, set[str]] = {arm: set() for arm in counts}
    for obs in observations:
        if obs.item:
            items_by_arm[obs.arm].add(obs.item)
    item_sets = list(items_by_arm.values())
    if not all(item_sets) or not set.intersection(*item_sets):
        return False
    universe = set().union(*item_sets)
    for arm, attempted in items_by_arm.items():
        missing = len(universe - attempted)
        if missing:
            counts[arm][NEVER_ATTEMPTED] = counts[arm].get(NEVER_ATTEMPTED, 0) + missing
    return True


def _spread(
    channel: str,
    count_by_arm: dict[str, int],
    total_by_arm: dict[str, int],
) -> ChannelSpread:
    """One channel's rates across arms, and the interval between its extremes."""
    rates = {
        arm: (count_by_arm[arm] / total) if (total := total_by_arm[arm]) else 0.0
        for arm in total_by_arm
    }
    # Stable sort, ends taken from opposite sides, so tied rates still name two arms.
    ordered = sorted(rates, key=lambda a: rates[a])
    lowest, highest = ordered[0], ordered[-1]
    lo, hi = rates[lowest], rates[highest]
    interval_low, interval_high = newcombe_interval(
        count_by_arm[highest],
        total_by_arm[highest],
        count_by_arm[lowest],
        total_by_arm[lowest],
    )
    return ChannelSpread(
        channel=channel,
        rate_by_arm=rates,
        lowest_arm=lowest,
        highest_arm=highest,
        ratio=float("inf") if lo == 0 else hi / lo,
        absolute_difference=hi - lo,
        interval_low=interval_low,
        interval_high=interval_high,
    )


def check_comparison(
    observations: Iterable[Observation],
    *,
    spread_ratio_threshold: float | None = None,
    minimum_absolute_difference: float | None = None,
    interval_max_width: float | None = None,
) -> ValidityReport:
    """Adjudicate whether a contrast across arms is sound enough to report.

    For every exclusion channel, and for the pooled left-for-any-reason rate, the arm with the
    highest rate is compared against the arm with the lowest:

    - **flagged** when the 95% Newcombe score interval on the rate difference excludes zero
      and the observed difference is at least `minimum_absolute_difference`. The floor exists
      because a real but sub-floor difference between two rates is unremarkable, however
      certain.
    - **inconclusive** when the interval spans zero but is wider than `interval_max_width`:
      the data cannot tell a real gap from none, and saying "sound" there would be a verdict
      the input never earned. `could_have_flagged` is False on such a report.
    - clean otherwise: the interval both spans zero and is narrow enough to have caught a gap.

    Items an arm never attempted, where the arms share an item vocabulary, are counted first as
    the `never_attempted` channel — absence is the largest exclusion channel there is. The
    pooled rate is skipped when only one channel exists, because it would repeat that channel's
    numbers exactly.

    `spread_ratio_threshold` is accepted for compatibility and **no longer decides**: the old
    rule (flag when ratio and difference both clear thresholds) passed a 40%-vs-25% gap and
    flagged one-timeout-in-five, so the interval replaced it. The ratio is still reported on
    every `ChannelSpread` as a diagnostic.

    The report always states how many arms, channels and observations were examined, so that a
    clean verdict from an input that could not have produced a finding is visible as such.

    A threshold left out is read from the limits (`AP_VALIDITY_MIN_ABSOLUTE_DIFFERENCE`,
    `AP_VALIDITY_INTERVAL_MAX_WIDTH`), so a deployment tunes it in one place for every surface
    that asks.
    """
    del spread_ratio_threshold  # accepted, documented above, decides nothing
    limits = get_limits()
    if minimum_absolute_difference is None:
        minimum_absolute_difference = limits.validity_min_absolute_difference
    if interval_max_width is None:
        interval_max_width = limits.validity_interval_max_width
    observations = list(observations)
    counts = missingness_by_arm(observations)
    arms = sorted(counts)
    item_sets_comparable = True
    if len(arms) >= 2:
        item_sets_comparable = _count_absence(counts, observations)
    totals = {arm: sum(channels.values()) for arm, channels in counts.items()}
    channels = sorted(
        {ch for channels_ in counts.values() for ch in channels_ if ch != INCLUDED}
    )

    flagged: list[ChannelSpread] = []
    inconclusive: list[ChannelSpread] = []
    if len(arms) >= 2:
        spreads = [
            _spread(ch, {arm: counts[arm].get(ch, 0) for arm in arms}, totals)
            for ch in channels
        ]
        if len(channels) >= 2:
            pooled = {arm: totals[arm] - counts[arm].get(INCLUDED, 0) for arm in arms}
            spreads.append(_spread(ANY_EXCLUSION, pooled, totals))
        for spread in spreads:
            if (
                spread.interval_low > 0
                and spread.absolute_difference >= minimum_absolute_difference
            ):
                flagged.append(spread)
            elif (
                spread.interval_low <= 0
                and spread.interval_high - spread.interval_low > interval_max_width
            ):
                inconclusive.append(spread)

    return ValidityReport(
        arms_examined=len(arms),
        channels_examined=len(channels),
        observations_examined=len(observations),
        flagged=flagged,
        paired_items=len(paired_items(observations)),
        total_items=len({obs.item for obs in observations}),
        flow=_flow_from_counts(counts),
        inconclusive=inconclusive,
        item_sets_comparable=item_sets_comparable,
    )


def _channel_as_dict(c: ChannelSpread) -> dict[str, Any]:
    """One channel spread as plain JSON values; an infinite ratio becomes ``None``."""
    return {
        "channel": c.channel,
        "rate_by_arm": c.rate_by_arm,
        "lowest_arm": c.lowest_arm,
        "highest_arm": c.highest_arm,
        "ratio": None if math.isinf(c.ratio) else c.ratio,
        "absolute_difference": c.absolute_difference,
        "interval_low": c.interval_low,
        "interval_high": c.interval_high,
        "description": c.describe(),
    }


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
        "item_sets_comparable": report.item_sets_comparable,
        "flagged": [_channel_as_dict(c) for c in report.flagged],
        "inconclusive": [_channel_as_dict(c) for c in report.inconclusive],
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
