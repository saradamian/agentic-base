"""What a comparison says, and how sure it is.

`domain.validity` answers whether a contrast between two arms is fair to report: whether runs
left each arm's denominator at the same rate. This module answers the next question: how large
is the difference, and how sure are we of it.

An excluded run has no outcome, and every way of handling that is a choice. So a contrast is
reported three ways:

- **Per protocol**: the tasks both arms scored. The difference carries its 95% interval and
  McNemar's exact test. Both arms finished these tasks, so they lean easy. The number compares
  the arms on them.
- **Intention to treat**: every task either arm attempted. An excluded run counts as a
  failure. This reading is lowest for the arm with more exclusions.
- **Bounds** (Manski, 1990): every excluded outcome set to its worst value, then to its best.
  They make no assumption about why runs were excluded, so a sign inside them is established.

When the interval spans zero, the contrast also reports the smallest effect the sample could
have detected. "p = 0.9" and "p = 0.9, and these pairs could only detect 40 points" are
different findings, and only the second can be read. Every reading is one of four: the arm
resolves more, resolves fewer, is equivalent within the margin, or the result is inconclusive.

McNemar (1947) is used in its exact binomial form. The interval is method 10 of Newcombe
(1998), "Improved confidence intervals for the difference between binomial proportions based on
paired data", Statistics in Medicine 17:2635-2650. It includes Newcombe's continuity
correction on the correlation. The tests pin both to published values. Standard library only, so the library
half keeps its dependency floor.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from statistics import NormalDist
from typing import Any, Protocol

from agentic_base.domain.validity import INCLUDED, wilson_interval
from agentic_base.limits import get_limits

_Z_95 = NormalDist().inv_cdf(0.975)
"""Two-sided 95% normal quantile. Full precision keeps the interval equal to published tables."""


class ScoredObservation(Protocol):
    """One run with its outcome. `adapters.LogObservation` satisfies it."""

    @property
    def item(self) -> str:
        """The task. Pairing key."""

    @property
    def arm(self) -> str:
        """The condition the task was run under."""

    @property
    def channel(self) -> str:
        """`validity.INCLUDED`, or how the run left the denominator."""

    @property
    def resolved(self) -> bool | None:
        """The outcome. None when the run has no verdict."""


def exact_mcnemar(only_treatment: int, only_baseline: int) -> float:
    """Two-sided exact McNemar test over the discordant pairs.

    Under no difference, each discordant pair is equally likely to favour either arm, so the
    smaller count is binomial with p = 1/2. The p-value doubles that tail and is capped at 1.
    The test is exact at every sample size. The chi-square approximation is too optimistic
    when few pairs disagree. The arithmetic stays in integers until the final division.
    """
    total = only_treatment + only_baseline
    if total == 0:
        return 1.0
    smaller = min(only_treatment, only_baseline)
    term, tail = 1, 1
    for i in range(smaller):
        term = term * (total - i) // (i + 1)
        tail += term
    return min(1.0, 2 * tail / 2**total)


def _corrected_correlation(
    both: float, only_t: float, only_b: float, neither: float
) -> float:
    """Newcombe's phi with its continuity correction (method 10).

    Zero when any margin of the 2x2 table is empty, because the correlation is then
    undefined. A positive association is reduced by n/2 and floored at zero; a negative one is
    left as it is.
    """
    n = both + only_t + only_b + neither
    margins = (both + only_t, only_b + neither, both + only_b, only_t + neither)
    if any(m == 0 for m in margins):
        return 0.0
    association = both * neither - only_t * only_b
    if association > n / 2:
        corrected = association - n / 2
    elif association >= 0:
        corrected = 0.0
    else:
        corrected = association
    return corrected / math.sqrt(margins[0] * margins[1] * margins[2] * margins[3])


def paired_difference_interval(
    both: float,
    only_treatment: float,
    only_baseline: float,
    neither: float,
    *,
    z: float = _Z_95,
) -> tuple[float, float]:
    """Newcombe's score interval for treatment minus baseline on paired outcomes.

    The four arguments are the cells of the paired table: tasks both arms resolved, tasks only
    the treatment resolved, tasks only the baseline resolved, and tasks neither did. Each
    arm's rate gets its Wilson interval, and the two are combined around the observed
    difference with a correction for the correlation between the arms. With no correlation it
    equals `validity.newcombe_interval`. That function gives the interval for independent
    samples.
    """
    n = both + only_treatment + only_baseline + neither
    if n <= 0:
        raise ValueError("an interval over zero pairs is not an interval")
    rate_t = (both + only_treatment) / n
    rate_b = (both + only_baseline) / n
    low_t, high_t = wilson_interval(both + only_treatment, n, z=z)
    low_b, high_b = wilson_interval(both + only_baseline, n, z=z)
    rho = _corrected_correlation(both, only_treatment, only_baseline, neither)
    below = (
        (rate_t - low_t) ** 2
        - 2 * rho * (rate_t - low_t) * (high_b - rate_b)
        + (high_b - rate_b) ** 2
    )
    above = (
        (rate_b - low_b) ** 2
        - 2 * rho * (rate_b - low_b) * (high_t - rate_t)
        + (high_t - rate_t) ** 2
    )
    difference = rate_t - rate_b
    return difference - math.sqrt(max(0.0, below)), difference + math.sqrt(
        max(0.0, above)
    )


def minimum_detectable_effect(
    pairs: int, discordant: int, *, alpha: float = 0.05, power: float = 0.80
) -> float | None:
    """The smallest difference these pairs could have detected. The result is a proportion.

    For a paired design the power comes from the discordant pairs. With d the share of pairs
    that disagree, the detectable difference is about (z for alpha/2 + z for power) times the
    square root of d / n. None when no pair disagrees. The sample then gives no estimate of
    the variance to plan from, and the interval is the better guide.
    """
    if pairs <= 0 or discordant <= 0:
        return None
    normal = NormalDist()
    z_sum = normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)
    return z_sum * math.sqrt((discordant / pairs) / pairs)


def holm(p_values: Sequence[float], *, alpha: float = 0.05) -> list[bool]:
    """Holm's step-down correction: which of several contrasts stay significant.

    Sorted from smallest p, the k-th is tested at alpha / (m - k). The first to fail stops the
    procedure, and every larger p fails with it.
    """
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    significant = [False] * len(p_values)
    for rank, index in enumerate(order):
        if p_values[index] > alpha / (len(p_values) - rank):
            break
        significant[index] = True
    return significant


@dataclass(frozen=True)
class PairedTable:
    """The paired 2x2 table over tasks both arms scored."""

    both: int
    only_treatment: int
    only_baseline: int
    neither: int

    @property
    def pairs(self) -> int:
        return self.both + self.only_treatment + self.only_baseline + self.neither

    @property
    def discordant(self) -> int:
        return self.only_treatment + self.only_baseline


@dataclass(frozen=True)
class Contrast:
    """One arm against the baseline, read three ways.

    Differences are proportions, so 0.10 is ten percentage points. Each difference is
    treatment minus baseline. When `declined` is not empty the contrast was not computed, and
    `declined` holds the reason.
    """

    baseline: str
    treatment: str
    declined: str = ""
    tasks: int = 0
    """Tasks either arm attempted: the intention-to-treat population."""

    table: PairedTable = PairedTable(0, 0, 0, 0)
    difference: float = 0.0
    interval: tuple[float, float] = (0.0, 0.0)
    p_value: float = 1.0
    detectable: float | None = None
    margin: float = 0.05
    excluded: int = 0
    """Runs with no outcome in either arm. A task one arm never attempted counts as an
    excluded run for that arm."""

    itt_difference: float = 0.0
    itt_p_value: float = 1.0
    bounds: tuple[float, float] = (0.0, 0.0)
    holm_significant: bool | None = None
    """Set when several arms are contrasted against one baseline. A single contrast leaves it
    None."""

    @property
    def reading(self) -> str:
        """Read from the per-protocol interval: `more`, `fewer`, `equivalent` or `inconclusive`."""
        low, high = self.interval
        if low > 0:
            return "more"
        if high < 0:
            return "fewer"
        if -self.margin < low and high < self.margin:
            return "equivalent"
        return "inconclusive"

    @property
    def sign_established(self) -> bool:
        """True when the bounds exclude zero. The sign then holds whatever the excluded runs
        would have done."""
        return self.bounds[0] > 0 or self.bounds[1] < 0

    def describe(self) -> str:
        """A few lines for a person to read. Each line carries one idea."""
        if self.declined:
            return f"{self.treatment} vs {self.baseline}: not compared, {self.declined}"
        low, high = self.interval
        pairs = self.table.pairs
        lines = [
            f"{self.treatment} vs {self.baseline}, {pairs} tasks both scored: "
            f"{_pp(self.difference)} (95% interval {_span(low, high)}), "
            f"exact McNemar p {_p(self.p_value)}"
        ]
        if self.reading in ("more", "fewer"):
            reading = f"{self.treatment} resolves {self.reading} tasks"
        elif self.reading == "equivalent":
            reading = f"equivalent within {self.margin * 100:.0f} pp"
        elif self.detectable is None:
            reading = "inconclusive: no pair disagrees, so there is nothing to test"
        else:
            reading = f"inconclusive: these pairs can only detect {self.detectable * 100:.0f} pp or more"
        if self.holm_significant is not None:
            reading += (
                "; significant after Holm"
                if self.holm_significant
                else "; not significant after Holm"
            )
        lines.append("  " + reading)
        if self.excluded == 0 and self.tasks == pairs:
            lines.append("  no run was excluded, so this is the whole result")
            return "\n".join(lines)
        lines.append(
            f"  excluded runs as failures, {self.tasks} tasks: {_pp(self.itt_difference)}, "
            f"p {_p(self.itt_p_value)}"
        )
        low, high = self.bounds
        sign = "keeps its sign" if self.sign_established else "may change sign"
        lines.append(
            f"  assuming nothing about the {self.excluded} excluded runs, the difference lies "
            f"between {low * 100:+.1f} and {high * 100:+.1f} pp and {sign}"
        )
        return "\n".join(lines)


def _pp(value: float) -> str:
    """A proportion as signed percentage points."""
    return f"{value * 100:+.1f} pp"


def _span(low: float, high: float) -> str:
    """Two proportions as a range of signed percentage points. `validity` prints its ranges
    the same way."""
    return f"{low * 100:+.1f} to {high * 100:+.1f} pp"


def _p(value: float) -> str:
    """A p-value that never prints a small one as zero."""
    if value < 0.001:
        return "< 0.001"
    return f"= {value:.3f}" if value < 0.01 else f"= {value:.2f}"


def contrast_arms(
    observations: Iterable[ScoredObservation],
    *,
    baseline: str,
    treatment: str,
    margin: float | None = None,
) -> Contrast:
    """Contrast `treatment` against `baseline`, task by task.

    The contrast declines when either arm has no runs, when the arms share no task, or when a
    task has more than one run in an arm. A declined contrast states its reason. A retried
    task has two outcomes. Which one counts is the caller's decision, and the caller should
    state it.

    `margin` is the equivalence margin as a proportion. Left out, it is read from the limits
    (`AP_CONTRAST_EQUIVALENCE_MARGIN`). Fix it before looking at the results.
    """
    if margin is None:
        margin = get_limits().contrast_equivalence_margin
    runs = [obs for obs in observations if obs.arm in (baseline, treatment)]
    by_arm: dict[str, dict[str, bool | None]] = defaultdict(dict)
    seen = Counter((obs.arm, obs.item) for obs in runs)
    repeated = sum(1 for count in seen.values() if count > 1)
    for arm in (baseline, treatment):
        if not any(obs.arm == arm for obs in runs):
            return Contrast(
                baseline, treatment, declined=f"{arm} has no runs", margin=margin
            )
    if repeated:
        return Contrast(
            baseline,
            treatment,
            declined=f"{repeated} task(s) have more than one run in an arm; keep one run per task and arm",
            margin=margin,
        )
    for obs in runs:
        by_arm[obs.arm][obs.item] = obs.resolved if obs.channel == INCLUDED else None
    shared = set(by_arm[baseline]) & set(by_arm[treatment])
    if not shared or not all(obs.item for obs in runs):
        return Contrast(
            baseline, treatment, declined="the arms share no task", margin=margin
        )

    tasks = sorted(set(by_arm[baseline]) | set(by_arm[treatment]))
    outcome_t = [by_arm[treatment].get(task) for task in tasks]
    outcome_b = [by_arm[baseline].get(task) for task in tasks]
    scored = [
        (t, b)
        for t, b in zip(outcome_t, outcome_b, strict=True)
        if t is not None and b is not None
    ]
    table = PairedTable(
        both=sum(1 for t, b in scored if t and b),
        only_treatment=sum(1 for t, b in scored if t and not b),
        only_baseline=sum(1 for t, b in scored if b and not t),
        neither=sum(1 for t, b in scored if not t and not b),
    )
    if table.pairs == 0:
        return Contrast(
            baseline,
            treatment,
            declined="no task was scored by both arms",
            margin=margin,
        )

    resolved_t = sum(1 for t in outcome_t if t)
    resolved_b = sum(1 for b in outcome_b if b)
    unknown_t = sum(1 for t in outcome_t if t is None)
    unknown_b = sum(1 for b in outcome_b if b is None)
    itt_only_t = sum(
        1 for t, b in zip(outcome_t, outcome_b, strict=True) if t and not b
    )
    itt_only_b = sum(
        1 for t, b in zip(outcome_t, outcome_b, strict=True) if b and not t
    )
    n = len(tasks)
    return Contrast(
        baseline=baseline,
        treatment=treatment,
        tasks=n,
        table=table,
        difference=(table.only_treatment - table.only_baseline) / table.pairs,
        interval=paired_difference_interval(
            table.both, table.only_treatment, table.only_baseline, table.neither
        ),
        p_value=exact_mcnemar(table.only_treatment, table.only_baseline),
        detectable=minimum_detectable_effect(table.pairs, table.discordant),
        margin=margin,
        excluded=unknown_t + unknown_b,
        itt_difference=(resolved_t - resolved_b) / n,
        itt_p_value=exact_mcnemar(itt_only_t, itt_only_b),
        bounds=(
            (resolved_t - (resolved_b + unknown_b)) / n,
            ((resolved_t + unknown_t) - resolved_b) / n,
        ),
    )


def contrast_against(
    observations: Iterable[ScoredObservation],
    *,
    baseline: str,
    margin: float | None = None,
) -> list[Contrast]:
    """Every other arm against `baseline`. With more than one, Holm's correction applies."""
    observations = list(observations)
    others = sorted({obs.arm for obs in observations} - {baseline})
    contrasts = [
        contrast_arms(observations, baseline=baseline, treatment=arm, margin=margin)
        for arm in others
    ]
    computed = [i for i, c in enumerate(contrasts) if not c.declined]
    if len(computed) < 2:
        return contrasts
    verdicts = holm([contrasts[i].p_value for i in computed])
    for i, verdict in zip(computed, verdicts, strict=True):
        contrasts[i] = replace(contrasts[i], holm_significant=verdict)
    return contrasts


def contrast_as_dict(contrast: Contrast) -> dict[str, Any]:
    """The contrast as plain JSON values."""
    return {
        "baseline": contrast.baseline,
        "treatment": contrast.treatment,
        "declined": contrast.declined or None,
        "tasks": contrast.tasks,
        "pairs": contrast.table.pairs,
        "table": {
            "both": contrast.table.both,
            "only_treatment": contrast.table.only_treatment,
            "only_baseline": contrast.table.only_baseline,
            "neither": contrast.table.neither,
        },
        "difference": contrast.difference,
        "interval": list(contrast.interval),
        "p_value": contrast.p_value,
        "detectable": contrast.detectable,
        "margin": contrast.margin,
        "reading": None if contrast.declined else contrast.reading,
        "excluded": contrast.excluded,
        "itt_difference": contrast.itt_difference,
        "itt_p_value": contrast.itt_p_value,
        "bounds": list(contrast.bounds),
        "sign_established": None if contrast.declined else contrast.sign_established,
        "holm_significant": contrast.holm_significant,
        "description": contrast.describe(),
    }
