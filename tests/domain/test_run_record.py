"""Behavioural tests for the run record."""

from agentic_base.domain.run_record import LabelSource, RunRecord, RunStatus


def _record(**kwargs) -> RunRecord:
    return RunRecord(tenant="hpml", **kwargs)


def test_an_unlabelled_run_is_not_citable() -> None:
    assert not _record(resolved=None).citable


def test_a_self_reported_outcome_is_not_citable() -> None:
    """An agent grading itself is not a measurement, however confident the claim."""
    record = _record(resolved=True, label_source=LabelSource.SELF_REPORTED)

    assert not record.citable


def test_a_convenience_verifier_outcome_is_not_citable() -> None:
    """Such checks err at rates that differ across arms, so they do not cancel in a contrast."""
    record = _record(resolved=True, label_source=LabelSource.CONVENIENCE_VERIFIER)

    assert not record.citable


def test_an_official_label_from_a_working_instrument_is_citable() -> None:
    record = _record(resolved=True, label_source=LabelSource.OFFICIAL_HARNESS)

    assert record.citable


def test_a_degraded_verdict_is_not_citable_even_from_an_official_source() -> None:
    """A scorer that failed open returns a result-shaped answer; the flag is what separates them."""
    record = _record(
        resolved=True, label_source=LabelSource.OFFICIAL_HARNESS, degraded=True
    )

    assert not record.citable


def test_a_completed_run_is_included_in_its_arms_denominator() -> None:
    record = _record(status=RunStatus.COMPLETED)

    assert not record.excluded
    assert record.exclusion_channel == "included"


def test_a_failed_run_counts_as_a_measurement_rather_than_an_exclusion() -> None:
    """The agent ran and did not succeed. That is the result, not a missing data point."""
    record = _record(status=RunStatus.FAILED)

    assert not record.excluded


def test_an_infrastructure_error_leaves_the_denominator_through_a_named_channel() -> (
    None
):
    record = _record(
        status=RunStatus.INFRASTRUCTURE_ERROR, failure_kind="container_removed"
    )

    assert record.excluded
    assert record.exclusion_channel == "container_removed"


def test_an_exclusion_without_detail_falls_back_to_its_status_as_the_channel() -> None:
    record = _record(status=RunStatus.TIMEOUT)

    assert record.exclusion_channel == "timeout"
