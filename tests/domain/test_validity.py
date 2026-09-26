"""Behavioural tests for the comparison-validity check.

The first test in this file is a **positive control** and it is the most important one here.
An earlier implementation of this idea in another codebase reported "clean" for weeks because
its per-arm rate dictionary was keyed off a leftover variable and could only ever hold one
entry. A validity check that cannot fail is worse than no validity check, because it gets
cited. If `test_flags_a_channel_whose_rate_differs_across_arms` ever stops failing on a
deliberately skewed input, this module is not measuring anything.

The block of tests named after driven failures pins the rewrite of the decision rule: each is
an input the previous rule (ratio over threshold AND difference over floor, per channel only)
got wrong, and each must stay red-capable for the reason its name states.
"""

from dataclasses import dataclass

import pytest

from agentic_base.domain.validity import (
    ANY_EXCLUSION,
    INCLUDED,
    NEVER_ATTEMPTED,
    check_comparison,
    flow_by_arm,
    missingness_by_arm,
    newcombe_interval,
    paired_items,
    render_flow,
    wilson_interval,
)


@dataclass(frozen=True)
class Obs:
    item: str
    arm: str
    channel: str


def _arm(
    arm: str, *, included: int, excluded: int, channel: str = "timeout"
) -> list[Obs]:
    rows = [Obs(item=f"i{n}", arm=arm, channel=INCLUDED) for n in range(included)]
    rows += [Obs(item=f"x{n}", arm=arm, channel=channel) for n in range(excluded)]
    return rows


def test_flags_a_channel_whose_rate_differs_across_arms() -> None:
    """POSITIVE CONTROL: a skewed exclusion rate must be reported as unsound."""
    observations = _arm("shallow", included=90, excluded=10) + _arm(
        "deep", included=99, excluded=1
    )

    report = check_comparison(observations)

    assert report.could_have_flagged
    assert not report.sound
    assert [c.channel for c in report.flagged] == ["timeout"]
    assert report.flagged[0].highest_arm == "shallow"


def test_reports_sound_when_exclusion_rates_match_across_arms() -> None:
    observations = _arm("shallow", included=90, excluded=10) + _arm(
        "deep", included=90, excluded=10
    )

    report = check_comparison(observations)

    assert report.could_have_flagged
    assert report.sound


def test_a_single_arm_cannot_produce_a_finding_and_says_so() -> None:
    """A clean verdict from an input that could not have flagged is not evidence."""
    report = check_comparison(_arm("only", included=50, excluded=50))

    assert report.sound
    assert not report.could_have_flagged
    assert "cannot produce a finding" in report.summary()


def test_no_exclusions_anywhere_cannot_produce_a_finding_and_says_so() -> None:
    observations = _arm("a", included=10, excluded=0) + _arm(
        "b", included=10, excluded=0
    )

    report = check_comparison(observations)

    assert report.channels_examined == 0
    assert not report.could_have_flagged


def test_forty_percent_versus_twenty_five_percent_exclusions_flag_despite_a_small_ratio() -> (
    None
):
    """POSITIVE CONTROL for the rewritten rule: the ratio here is 1.6, under the old 2.0
    threshold, so the old rule reported a fifteen-point MNAR gap at n=1000 per arm as sound.
    The interval on the difference excludes zero decisively, so it must flag."""
    observations = [
        Obs(f"t{n}", "a", "timeout" if n < 400 else INCLUDED) for n in range(1000)
    ]
    observations += [
        Obs(f"t{n}", "b", "timeout" if n < 250 else INCLUDED) for n in range(1000)
    ]

    report = check_comparison(observations)

    assert not report.sound
    assert [c.channel for c in report.flagged] == ["timeout"]
    assert report.flagged[0].ratio == pytest.approx(1.6)
    assert report.flagged[0].interval_low > 0


def test_exclusions_split_across_free_text_channel_names_cannot_dilute_the_pooled_rate() -> (
    None
):
    """POSITIVE CONTROL for the rewritten rule: 12% of one arm lost across twelve
    differently-worded timeout strings is 1% in every row of the per-channel table, under the
    absolute floor, and the old per-channel-only rule reported it sound. The pooled
    left-for-any-reason rate is what free text cannot dilute."""
    observations = [
        Obs(f"t{n}", "a", f"timeout after {600 + n}s" if n < 12 else INCLUDED)
        for n in range(100)
    ]
    observations += [Obs(f"t{n}", "b", INCLUDED) for n in range(100)]

    report = check_comparison(observations)

    assert not report.sound
    assert [c.channel for c in report.flagged] == [ANY_EXCLUSION]
    assert report.flagged[0].interval_low > 0


def test_one_timeout_in_five_runs_is_too_little_data_not_a_finding() -> None:
    """The old rule flagged this: 20% against 0% is an infinite ratio, and there was no
    minimum evidence, so noise at n=5 became a finding. The interval spans zero and is far
    wider than any gap it could confirm, so the honest verdict is neither sound nor unsound."""
    observations = [Obs("t0", "a", "timeout")]
    observations += [Obs(f"t{n}", "a", INCLUDED) for n in range(1, 5)]
    observations += [Obs(f"t{n}", "b", INCLUDED) for n in range(5)]

    report = check_comparison(observations)

    assert not report.flagged
    assert not report.could_have_flagged
    assert report.summary().startswith("inconclusive: too little data")
    assert [c.channel for c in report.inconclusive] == ["timeout"]


def test_items_one_arm_never_attempted_are_counted_as_exclusions() -> None:
    """POSITIVE CONTROL for the rewritten rule: one arm ran only half the shared task set and
    reported zero exclusions. Under the old rule what was never attempted was invisible — the
    largest MNAR channel there is. It is an exclusion channel like any other."""
    observations = [Obs(f"t{n}", "a", INCLUDED) for n in range(100)]
    observations += [Obs(f"t{n}", "b", INCLUDED) for n in range(50)]

    report = check_comparison(observations)

    assert not report.sound
    assert [c.channel for c in report.flagged] == [NEVER_ATTEMPTED]
    assert report.flow["b"].excluded == {NEVER_ATTEMPTED: 50}
    assert report.flow["b"].assessed == 100


def test_arms_with_disjoint_item_sets_are_said_to_be_incomparable() -> None:
    """Two arms that share no items are running different task sets; counting absence there
    would flag everything, and staying silent would compare apples with oranges."""
    observations = [Obs(f"a{n}", "a", INCLUDED) for n in range(10)]
    observations += [Obs(f"b{n}", "b", INCLUDED) for n in range(10)]

    report = check_comparison(observations)

    assert not report.item_sets_comparable
    assert "share no items" in report.summary()


def test_observations_without_item_keys_do_not_pretend_absence_was_counted() -> None:
    observations = [Obs("", "a", INCLUDED) for _ in range(10)]
    observations += [Obs("", "b", INCLUDED) for _ in range(10)]

    report = check_comparison(observations)

    assert not report.item_sets_comparable
    assert "share no items" in report.summary()


def test_a_flagged_channel_describes_its_interval() -> None:
    """The interval is the decision; a description without it asks to be taken on faith."""
    observations = [
        Obs(f"t{n}", "a", "timeout" if n < 10 else INCLUDED) for n in range(100)
    ] + [Obs(f"t{n}", "b", INCLUDED) for n in range(100)]

    report = check_comparison(observations)

    assert "95% interval" in report.flagged[0].describe()
    assert "pp" in report.flagged[0].describe()


def test_wilson_interval_matches_published_reference_values() -> None:
    """Reference: Newcombe (1998), Statistics in Medicine 17:857-872, Table I worked example,
    81/263 under the Wilson score method: 0.2553 to 0.3662. The zero-count boundary has the
    closed form (0, z²/(n+z²)): for 0/5 at z=1.96 that is 3.8416/8.8416 = 0.43449."""
    low, high = wilson_interval(81, 263)
    assert low == pytest.approx(0.2553, abs=5e-4)
    assert high == pytest.approx(0.3662, abs=5e-4)

    low, high = wilson_interval(0, 5)
    assert low == 0.0
    assert high == pytest.approx(3.8416 / 8.8416, abs=1e-5)

    assert wilson_interval(2, 2)[1] == 1.0


def test_an_interval_over_zero_observations_is_refused() -> None:
    with pytest.raises(ValueError):
        wilson_interval(0, 0)


def test_newcombe_interval_matches_published_reference_values() -> None:
    """Reference: Newcombe (1998), Statistics in Medicine 17:873-890, Table II, method 10
    (Wilson intervals combined square-and-add), at z = 1.96:
    (a) 56/70 - 48/80 → 0.0524 to 0.3339; (b) 9/10 - 3/10 → 0.1705 to 0.8090;
    (d) 5/56 - 0/29 → -0.0381 to 0.1926; (e) 0/10 - 0/20 → -0.1611 to 0.2775."""
    cases = [
        ((56, 70, 48, 80), (0.0524, 0.3339)),
        ((9, 10, 3, 10), (0.1705, 0.8090)),
        ((5, 56, 0, 29), (-0.0381, 0.1926)),
        ((0, 10, 0, 20), (-0.1611, 0.2775)),
    ]
    for args, (low, high) in cases:
        got_low, got_high = newcombe_interval(*args)
        assert got_low == pytest.approx(low, abs=5e-4), args
        assert got_high == pytest.approx(high, abs=5e-4), args


def test_ignores_a_ratio_between_two_negligible_rates() -> None:
    """Two rare exclusions differing threefold are noise, not a finding."""
    observations = _arm("a", included=999, excluded=3) + _arm(
        "b", included=1000, excluded=1
    )

    report = check_comparison(observations)

    assert report.sound


def test_treats_a_zero_rate_against_a_real_one_as_an_infinite_ratio() -> None:
    observations = _arm("a", included=80, excluded=20) + _arm(
        "b", included=100, excluded=0
    )

    report = check_comparison(observations)

    assert not report.sound
    assert report.flagged[0].ratio == float("inf")


def test_counts_each_exclusion_channel_separately_per_arm() -> None:
    observations = _arm("a", included=8, excluded=2, channel="timeout") + _arm(
        "b", included=8, excluded=2, channel="infrastructure_error"
    )

    counts = missingness_by_arm(observations)

    assert counts["a"]["timeout"] == 2
    assert "timeout" not in counts["b"]
    assert counts["b"]["infrastructure_error"] == 2


def test_paired_items_are_those_every_arm_included() -> None:
    observations = [
        Obs("shared", "a", INCLUDED),
        Obs("shared", "b", INCLUDED),
        Obs("only-a", "a", INCLUDED),
        Obs("only-a", "b", "timeout"),
    ]

    assert paired_items(observations) == {"shared"}


def test_paired_items_is_empty_when_an_arm_included_nothing() -> None:
    """An arm that scored nothing has no intersection with the others, and must not be
    silently dropped from the pairing."""
    observations = [Obs("i", "a", INCLUDED), Obs("i", "b", "timeout")]

    assert paired_items(observations) == set()


def test_report_states_how_much_it_examined_so_a_zero_is_legible() -> None:
    observations = _arm("a", included=5, excluded=1) + _arm("b", included=5, excluded=1)

    report = check_comparison(observations)

    assert report.arms_examined == 2
    assert report.channels_examined == 1
    assert report.observations_examined == 12


def test_flow_reconciles_assessed_with_analysed_plus_every_exclusion() -> None:
    """The CONSORT invariant: nobody assessed goes unaccounted for."""
    obs = _arm("a", included=7, excluded=3) + _arm(
        "a", included=0, excluded=2, channel="oom"
    )
    flow = flow_by_arm(obs)
    row = flow["a"]
    assert row.assessed == 12
    assert row.analysed == 7
    assert row.excluded == {"timeout": 3, "oom": 2}
    assert row.assessed == row.analysed + sum(row.excluded.values())


def test_flow_names_each_reason_per_arm_so_a_reader_can_check_the_verdict() -> None:
    obs = _arm("a", included=8, excluded=2) + _arm(
        "b", included=9, excluded=1, channel="oom"
    )
    text = render_flow(flow_by_arm(obs))
    assert "a: assessed 10; excluded 2 (2 timeout); analysed 8" in text
    assert "b: assessed 10; excluded 1 (1 oom); analysed 9" in text


def test_a_sound_verdict_still_carries_the_accounting_it_rests_on() -> None:
    """A clean result with no flow would be a verdict without evidence. The arms are large
    enough that the interval is narrow: at ten runs each this would be too little data."""
    report = check_comparison(
        _arm("a", included=90, excluded=10) + _arm("b", included=90, excluded=10)
    )
    assert report.sound
    assert report.could_have_flagged
    assert set(report.flow) == {"a", "b"}
    assert (
        report.flow["a"].describe()
        == "a: assessed 100; excluded 10 (10 timeout); analysed 90"
    )
