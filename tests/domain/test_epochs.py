"""Declaring and enforcing epoch boundaries."""

from datetime import datetime, timedelta, timezone

from app.domain.epochs import Epoch, MeaningChange, check_poolable, classify
from app.domain.run_record import RunRecord

LANDED = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _change() -> MeaningChange:
    return MeaningChange(
        commit="deadbee",
        subject="scorer",
        description="the default scorer changed from the in-tree check to the official harness",
        effective_at=LANDED,
    )


def _record(*, revision: str = "abc1234", offset_days: int = 0) -> RunRecord:
    return RunRecord(
        tenant="hpml",
        code_revision=revision,
        created_at=LANDED + timedelta(days=offset_days),
    )


def test_a_record_from_before_the_commit_is_placed_before() -> None:
    assert classify(_record(offset_days=-3), _change()) is Epoch.BEFORE


def test_a_record_from_after_the_commit_is_placed_after() -> None:
    assert classify(_record(offset_days=3), _change()) is Epoch.AFTER


def test_the_declaring_commit_itself_is_on_the_new_side() -> None:
    """The commit is the first to carry the new meaning, whatever its timestamp says."""
    assert (
        classify(_record(revision="deadbee", offset_days=-99), _change()) is Epoch.AFTER
    )


def test_a_record_with_no_code_revision_cannot_be_placed() -> None:
    """Guessing here is how a corpus quietly mixes two populations."""
    assert classify(_record(revision=""), _change()) is Epoch.UNKNOWN


def test_records_on_one_side_may_be_pooled() -> None:
    records = [_record(offset_days=n) for n in (1, 2, 3)]

    verdict = check_poolable(records, _change())

    assert verdict.poolable
    assert verdict.counts[Epoch.AFTER] == 3


def test_records_that_straddle_the_boundary_may_not_be_pooled() -> None:
    records = [_record(offset_days=-1), _record(offset_days=1)]

    verdict = check_poolable(records, _change())

    assert not verdict.poolable
    assert "straddle" in verdict.reason


def test_a_single_unplaceable_record_blocks_pooling() -> None:
    """The refusal that feels excessive is the one that pays."""
    records = [_record(offset_days=1), _record(offset_days=2), _record(revision="")]

    verdict = check_poolable(records, _change())

    assert not verdict.poolable
    assert "cannot be placed" in verdict.reason


def test_an_empty_set_reports_itself_as_inconclusive() -> None:
    verdict = check_poolable([], _change())

    assert verdict.records_examined == 0
    assert "inconclusive" in verdict.summary()


def _component_change() -> MeaningChange:
    return MeaningChange(
        commit="cafe123",
        subject="validity threshold",
        description="the default spread ratio changed",
        effective_at=LANDED,
        component="agentic-base",
        min_version="0.3.0",
    )


def _with_versions(**versions: str) -> RunRecord:
    return RunRecord(
        tenant="hpml", code_revision="abc1234", component_versions=dict(versions)
    )


def test_a_run_on_an_older_component_version_is_placed_before() -> None:
    assert (
        classify(_with_versions(**{"agentic-base": "0.2.9"}), _component_change())
        is Epoch.BEFORE
    )


def test_a_run_on_the_first_changed_version_is_placed_after() -> None:
    assert (
        classify(_with_versions(**{"agentic-base": "0.3.0"}), _component_change())
        is Epoch.AFTER
    )


def test_a_run_that_recorded_no_version_for_that_component_cannot_be_placed() -> None:
    """The case that appears the moment an application imports a library that moves underneath it.

    A configuration fingerprint governs flags and cannot see the version of imported code, so two
    runs can share a fingerprint and a revision and still have run different software.
    """
    assert (
        classify(_with_versions(**{"something-else": "1.0.0"}), _component_change())
        is Epoch.UNKNOWN
    )


def test_a_version_that_cannot_be_read_yields_no_placement_rather_than_a_guess() -> (
    None
):
    assert (
        classify(_with_versions(**{"agentic-base": "main"}), _component_change())
        is Epoch.UNKNOWN
    )


def test_component_runs_that_straddle_a_version_boundary_may_not_be_pooled() -> None:
    records = [
        _with_versions(**{"agentic-base": "0.2.9"}),
        _with_versions(**{"agentic-base": "0.3.1"}),
    ]

    assert not check_poolable(records, _component_change()).poolable
