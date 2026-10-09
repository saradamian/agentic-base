"""The contrast: published values first, then what it says about real runs.

Every number asserted here comes from outside the module: a published table, a binomial tail
worked by hand, or the committed example runs. A test that recomputed the formula would pass
whatever the formula said.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pytest

from agentic_base.adapters import from_jsonl
from agentic_base.domain.contrast import (
    _Z_95,
    contrast_against,
    contrast_arms,
    contrast_as_dict,
    exact_mcnemar,
    holm,
    minimum_detectable_effect,
    paired_difference_interval,
)
from agentic_base.domain.validity import INCLUDED, newcombe_interval

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "results.jsonl"


@dataclass(frozen=True)
class Run:
    item: str
    arm: str
    channel: str = INCLUDED
    resolved: bool | None = None


def _runs(arm: str, outcomes: dict[str, bool | None]) -> list[Run]:
    """One run per task; None stands for a run that timed out."""
    return [
        Run(task, arm, INCLUDED, outcome)
        if outcome is not None
        else Run(task, arm, "timeout")
        for task, outcome in outcomes.items()
    ]


def _paired(both: int, only_t: int, only_b: int, neither: int) -> list[Run]:
    """Runs whose per-protocol table is exactly the four counts given."""
    cells = (
        [(True, True)] * both
        + [(True, False)] * only_t
        + [(False, True)] * only_b
        + [(False, False)] * neither
    )
    runs: list[Run] = []
    for i, (t, b) in enumerate(cells):
        runs += [
            Run(f"t{i}", "treatment", INCLUDED, t),
            Run(f"t{i}", "baseline", INCLUDED, b),
        ]
    return runs


# --- exact McNemar -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("only_treatment", "only_baseline", "expected"),
    [
        (0, 5, 2 * 1 / 32),  # tail C(5,0) over 2^5, doubled
        (1, 9, 2 * (1 + 10) / 1024),
        (2, 8, 2 * (1 + 10 + 45) / 1024),
        (3, 3, 1.0),  # doubled tail exceeds one and is capped
        (0, 0, 1.0),  # no discordant pair, nothing to test
    ],
)
def test_exact_mcnemar_equals_the_doubled_binomial_tail_worked_by_hand(
    only_treatment: int, only_baseline: int, expected: float
) -> None:
    assert exact_mcnemar(only_treatment, only_baseline) == pytest.approx(
        expected, rel=1e-12
    )


def test_exact_mcnemar_does_not_depend_on_which_arm_won() -> None:
    assert exact_mcnemar(2, 11) == exact_mcnemar(11, 2)


def test_exact_mcnemar_stays_exact_with_thousands_of_discordant_pairs() -> None:
    p = exact_mcnemar(1_000, 1_100)
    assert 0.0 < p < 0.05


# --- the paired interval -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "pt", "ps", "rho", "below", "above"),
    [
        (371, 0.5, 0.41, 0.51, 0.05044, 0.04954),
        (289, 0.5, 0.41, 0.62, 0.05050, 0.04949),
        (364, 0.6, 0.41, 0.51, 0.05094, 0.04897),
        (284, 0.6, 0.41, 0.62, 0.05104, 0.04881),
        (343, 0.7, 0.41, 0.51, 0.05149, 0.04842),
    ],
)
def test_paired_interval_reproduces_the_published_ncss_segment_widths(
    n: int, pt: float, ps: float, rho: float, below: float, above: float
) -> None:
    """PASS chapter 102, page 102-8: Newcombe's score method from planning values.

    The planning values give expected cell counts through the identities on page 102-5;
    the published widths are the distances from the difference to each limit.
    """
    spread = rho * math.sqrt(pt * ps * (1 - pt) * (1 - ps))
    both = n * (pt * ps + spread)
    only_t = n * (pt * (1 - ps) - spread)
    only_b = n * ((1 - pt) * ps - spread)
    neither = n * ((1 - pt) * (1 - ps) + spread)

    low, high = paired_difference_interval(both, only_t, only_b, neither)

    assert round((pt - ps) - low, 5) == below
    assert round(high - (pt - ps), 5) == above


def test_paired_interval_is_the_independent_one_when_the_correlation_corrects_to_zero() -> (
    None
):
    # association 6*4 - 8*2 = 8 is below n/2 = 10, so the corrected correlation is zero
    paired = paired_difference_interval(6, 8, 2, 4)
    independent = newcombe_interval(14, 20, 8, 20, z=_Z_95)

    assert paired == pytest.approx(independent, abs=1e-12)


def test_paired_interval_always_contains_the_observed_difference() -> None:
    for both in range(4):
        for only_t in range(4):
            for only_b in range(4):
                for neither in range(4):
                    n = both + only_t + only_b + neither
                    if n == 0:
                        continue
                    low, high = paired_difference_interval(
                        both, only_t, only_b, neither
                    )
                    assert low <= (only_t - only_b) / n <= high


def test_paired_interval_refuses_zero_pairs() -> None:
    with pytest.raises(ValueError):
        paired_difference_interval(0, 0, 0, 0)


# --- power and multiplicity ----------------------------------------------------------------


def test_minimum_detectable_effect_grows_as_the_share_of_disagreeing_pairs_grows() -> (
    None
):
    # (z_0.975 + z_0.80) * sqrt(0.2 / 100) = 2.801585 * 0.0447214
    fifth = minimum_detectable_effect(100, 20)
    two_fifths = minimum_detectable_effect(100, 40)
    assert fifth is not None and two_fifths is not None
    assert fifth == pytest.approx(0.125291, abs=1e-6)
    assert two_fifths > fifth


def test_minimum_detectable_effect_is_undefined_when_no_pair_disagrees() -> None:
    assert minimum_detectable_effect(100, 0) is None
    assert minimum_detectable_effect(0, 0) is None


def test_holm_keeps_every_contrast_when_each_clears_its_threshold() -> None:
    assert holm([0.001, 0.002]) == [True, True]


def test_holm_stops_at_the_first_p_value_that_fails_its_threshold() -> None:
    # 0.005 <= 0.05/4 and 0.01 <= 0.05/3 pass; 0.03 > 0.05/2 stops the procedure
    assert holm([0.01, 0.04, 0.03, 0.005]) == [True, False, False, True]


# --- what the contrast says ----------------------------------------------------------------


def test_the_committed_example_is_inconclusive_per_protocol_and_bounded_above_zero() -> (
    None
):
    """Forty runs, six with-planner timeouts against one baseline timeout."""
    contrast = contrast_arms(
        from_jsonl(EXAMPLE, arm="config"), baseline="baseline", treatment="with-planner"
    )

    assert (contrast.table.both, contrast.table.only_treatment) == (10, 2)
    assert (contrast.table.only_baseline, contrast.table.neither) == (0, 2)
    assert contrast.difference == pytest.approx(2 / 14)
    assert contrast.p_value == pytest.approx(0.5)
    assert contrast.reading == "inconclusive"
    assert contrast.tasks == 20
    assert contrast.excluded == 7
    assert contrast.itt_difference == pytest.approx(0.10)
    assert contrast.bounds == pytest.approx((0.05, 0.40))
    assert contrast.sign_established


def test_swapping_the_arms_flips_every_sign_and_nothing_else() -> None:
    runs = from_jsonl(EXAMPLE, arm="config")
    ahead = contrast_arms(runs, baseline="baseline", treatment="with-planner")
    behind = contrast_arms(runs, baseline="with-planner", treatment="baseline")

    assert behind.difference == pytest.approx(-ahead.difference)
    assert behind.interval == pytest.approx((-ahead.interval[1], -ahead.interval[0]))
    assert behind.bounds == pytest.approx((-ahead.bounds[1], -ahead.bounds[0]))
    assert behind.p_value == ahead.p_value


def test_a_clear_difference_reads_as_more_and_names_the_arm() -> None:
    contrast = contrast_arms(
        _paired(40, 30, 5, 25), baseline="baseline", treatment="treatment"
    )

    assert contrast.reading == "more"
    assert "treatment resolves more tasks" in contrast.describe()


def test_a_tight_interval_inside_the_margin_reads_as_equivalent() -> None:
    contrast = contrast_arms(
        _paired(500, 10, 12, 478),
        baseline="baseline",
        treatment="treatment",
        margin=0.05,
    )

    assert contrast.reading == "equivalent"


def test_an_inconclusive_result_states_what_the_sample_could_have_detected() -> None:
    contrast = contrast_arms(
        _paired(5, 2, 1, 2), baseline="baseline", treatment="treatment"
    )

    assert contrast.reading == "inconclusive"
    assert "can only detect" in contrast.describe()


def test_no_reading_ever_says_no_effect() -> None:
    for table in ((5, 2, 1, 2), (40, 30, 5, 25), (500, 10, 12, 478), (5, 0, 0, 5)):
        text = contrast_arms(
            _paired(*table), baseline="baseline", treatment="treatment"
        ).describe()
        assert "no effect" not in text


def test_with_nothing_excluded_the_bounds_collapse_onto_the_per_protocol_difference() -> (
    None
):
    contrast = contrast_arms(
        _paired(5, 2, 1, 2), baseline="baseline", treatment="treatment"
    )

    assert contrast.excluded == 0
    assert contrast.bounds == pytest.approx((contrast.difference, contrast.difference))
    assert "no run was excluded" in contrast.describe()


def test_a_run_outside_the_included_channel_has_no_outcome_even_if_it_carries_one() -> (
    None
):
    runs = _runs("baseline", {"a": True, "b": False}) + [
        Run("a", "treatment", INCLUDED, True),
        Run(
            "b", "treatment", "timeout", True
        ),  # a verdict on an excluded run is not used
    ]
    contrast = contrast_arms(runs, baseline="baseline", treatment="treatment")

    assert contrast.table.pairs == 1
    assert contrast.excluded == 1


def test_a_task_never_attempted_by_one_arm_counts_as_excluded_for_that_arm() -> None:
    runs = _runs("baseline", {"a": True, "b": False, "c": True}) + _runs(
        "treatment", {"a": True, "b": True}
    )
    contrast = contrast_arms(runs, baseline="baseline", treatment="treatment")

    assert contrast.tasks == 3
    assert contrast.excluded == 1


def test_declines_when_a_task_has_two_runs_in_one_arm() -> None:
    runs = _paired(3, 1, 1, 1) + [Run("t0", "treatment", INCLUDED, False)]
    contrast = contrast_arms(runs, baseline="baseline", treatment="treatment")

    assert contrast.declined
    assert "more than one run" in contrast.describe()


def test_declines_when_the_arms_share_no_task() -> None:
    runs = _runs("baseline", {"a": True}) + _runs("treatment", {"b": True})

    assert contrast_arms(runs, baseline="baseline", treatment="treatment").declined


def test_declines_when_an_arm_has_no_runs() -> None:
    contrast = contrast_arms(
        _runs("baseline", {"a": True}), baseline="baseline", treatment="x"
    )

    assert contrast.declined == "x has no runs"


def test_several_arms_against_one_baseline_are_corrected_with_holm() -> None:
    runs = _paired(40, 30, 5, 25)
    runs += [
        Run(r.item, "second", r.channel, r.resolved)
        for r in runs
        if r.arm == "baseline"
    ]

    contrasts = contrast_against(runs, baseline="baseline")

    assert [c.treatment for c in contrasts] == ["second", "treatment"]
    assert all(c.holm_significant is not None for c in contrasts)
    assert contrasts[1].holm_significant is True


def test_each_line_states_whether_its_difference_survived_holm() -> None:
    runs = _paired(40, 30, 5, 25)
    runs += [
        Run(r.item, "second", r.channel, r.resolved)
        for r in runs
        if r.arm == "baseline"
    ]

    second, treatment = contrast_against(runs, baseline="baseline")

    assert "; not significant after Holm" in second.describe()
    assert "; significant after Holm" in treatment.describe()


def test_declines_when_the_arms_share_tasks_but_none_was_scored_by_both() -> None:
    runs = _runs("baseline", {"a": True, "b": False}) + _runs(
        "treatment", {"a": None, "b": None}
    )
    contrast = contrast_arms(runs, baseline="baseline", treatment="treatment")

    assert contrast.declined == "no task was scored by both arms"


def test_a_single_contrast_carries_no_holm_verdict() -> None:
    (contrast,) = contrast_against(_paired(5, 2, 1, 2), baseline="baseline")

    assert contrast.holm_significant is None


def test_the_contrast_serialises_to_strict_json() -> None:
    runs = from_jsonl(EXAMPLE, arm="config")
    for contrast in (
        contrast_arms(runs, baseline="baseline", treatment="with-planner"),
        contrast_arms(_paired(5, 0, 0, 5), baseline="baseline", treatment="treatment"),
        contrast_arms(runs, baseline="baseline", treatment="missing"),
    ):
        json.dumps(contrast_as_dict(contrast), allow_nan=False)
