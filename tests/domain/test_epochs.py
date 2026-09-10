"""Declaring and enforcing epoch boundaries."""

from datetime import UTC, datetime, timedelta

from app.domain.epochs import Epoch, MeaningChange, check_poolable, classify
from app.domain.run_record import RunRecord

LANDED = datetime(2026, 9, 1, tzinfo=UTC)


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
    assert classify(_record(revision="deadbee", offset_days=-99), _change()) is Epoch.AFTER


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
