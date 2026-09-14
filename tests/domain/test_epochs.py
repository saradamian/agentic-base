"""Declaring and enforcing epoch boundaries."""

from datetime import datetime, timedelta, timezone

from agentic_base.domain.epochs import (
    Epoch,
    MeaningChange,
    VersionEpochs,
    check_poolable,
    classify,
    version_key,
)
from agentic_base.domain.run_record import RunRecord

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


BASE_03 = "surf-agentic-base=0.3.4"
BASE_04 = "surf-agentic-base=0.4.0"
BASE_06 = "surf-agentic-base=0.6.0"
EPOCHS = VersionEpochs(epochs=(frozenset({"", BASE_03, BASE_04}), frozenset({BASE_06})))


def _run_on(**versions: str) -> RunRecord:
    return RunRecord(
        tenant="hpml", code_revision="abc1234", component_versions=dict(versions)
    )


def test_a_version_key_is_stable_and_empty_for_a_run_that_recorded_none() -> None:
    assert version_key({"b": "2", "a": "1"}) == "a=1,b=2"
    assert version_key({}) == version_key(None) == ""


def test_versions_declared_in_one_epoch_pool_with_the_runs_recorded_before_versions() -> (
    None
):
    verdict = EPOCHS.check(["", BASE_03, BASE_04])

    assert verdict.poolable
    assert verdict.keys_examined == 3


def test_versions_from_two_declared_epochs_may_not_pool() -> None:
    verdict = EPOCHS.check([BASE_04, BASE_06])

    assert not verdict.poolable
    assert verdict.epochs_spanned == 2


def test_a_version_nobody_declared_is_refused_however_close_it_is() -> None:
    """A boundary model would have put 0.4.1 on a side without anyone reviewing the release."""
    verdict = EPOCHS.check([BASE_04, "surf-agentic-base=0.4.1"])

    assert not verdict.poolable
    assert verdict.undeclared == ("surf-agentic-base=0.4.1",)


def test_runs_that_recorded_no_versions_pool_only_if_an_epoch_declares_them() -> None:
    assert (
        not VersionEpochs(epochs=(frozenset({BASE_06}),)).check(["", BASE_06]).poolable
    )


def test_no_versions_examined_is_inconclusive_rather_than_poolable() -> None:
    verdict = EPOCHS.check([])

    assert not verdict.could_have_failed
    assert verdict.summary().startswith("inconclusive")


def test_records_are_checked_by_the_versions_they_recorded() -> None:
    same = [_run_on(), _run_on(**{"surf-agentic-base": "0.4.0"})]
    across = [
        _run_on(**{"surf-agentic-base": "0.4.0"}),
        _run_on(**{"surf-agentic-base": "0.6.0"}),
    ]

    assert EPOCHS.check_records(same).poolable
    assert not EPOCHS.check_records(across).poolable
