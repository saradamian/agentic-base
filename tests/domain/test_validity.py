"""Behavioural tests for the comparison-validity check.

The first test in this file is a **positive control** and it is the most important one here.
An earlier implementation of this idea in another codebase reported "clean" for weeks because
its per-arm rate dictionary was keyed off a leftover variable and could only ever hold one
entry. A validity check that cannot fail is worse than no validity check, because it gets
cited. If `test_flags_a_channel_whose_rate_differs_across_arms` ever stops failing on a
deliberately skewed input, this module is not measuring anything.
"""

from dataclasses import dataclass

from app.domain.validity import INCLUDED, check_comparison, missingness_by_arm, paired_items


@dataclass(frozen=True)
class Obs:
    item: str
    arm: str
    channel: str


def _arm(arm: str, *, included: int, excluded: int, channel: str = "timeout") -> list[Obs]:
    rows = [Obs(item=f"i{n}", arm=arm, channel=INCLUDED) for n in range(included)]
    rows += [Obs(item=f"x{n}", arm=arm, channel=channel) for n in range(excluded)]
    return rows


def test_flags_a_channel_whose_rate_differs_across_arms() -> None:
    """POSITIVE CONTROL: a skewed exclusion rate must be reported as unsound."""
    observations = _arm("shallow", included=90, excluded=10) + _arm("deep", included=99, excluded=1)

    report = check_comparison(observations)

    assert report.could_have_flagged
    assert not report.sound
    assert [c.channel for c in report.flagged] == ["timeout"]
    assert report.flagged[0].highest_arm == "shallow"


def test_reports_sound_when_exclusion_rates_match_across_arms() -> None:
    observations = _arm("shallow", included=90, excluded=10) + _arm("deep", included=90, excluded=10)

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
    observations = _arm("a", included=10, excluded=0) + _arm("b", included=10, excluded=0)

    report = check_comparison(observations)

    assert report.channels_examined == 0
    assert not report.could_have_flagged


def test_ignores_a_ratio_between_two_negligible_rates() -> None:
    """Two rare exclusions differing threefold are noise, not a finding."""
    observations = _arm("a", included=999, excluded=3) + _arm("b", included=1000, excluded=1)

    report = check_comparison(observations)

    assert report.sound


def test_treats_a_zero_rate_against_a_real_one_as_an_infinite_ratio() -> None:
    observations = _arm("a", included=80, excluded=20) + _arm("b", included=100, excluded=0)

    report = check_comparison(observations)

    assert not report.sound
    assert report.flagged[0].ratio == float("inf")


def test_counts_each_exclusion_channel_separately_per_arm() -> None:
    observations = (
        _arm("a", included=8, excluded=2, channel="timeout")
        + _arm("b", included=8, excluded=2, channel="infrastructure_error")
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
