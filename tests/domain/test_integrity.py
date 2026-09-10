"""The hash chain over run records."""

from app.domain.integrity import GENESIS, build_chain, content_hash, verify_chain
from app.domain.run_record import LabelSource, RunRecord


def _records(n: int) -> list[RunRecord]:
    return [RunRecord(tenant="hpml", item=f"task-{i}", arm="baseline") for i in range(n)]


def test_the_same_record_hashes_the_same_way_every_time() -> None:
    record = _records(1)[0]

    assert content_hash(record) == content_hash(record)


def test_changing_an_audit_field_changes_the_hash() -> None:
    record = _records(1)[0]
    before = content_hash(record)

    record.label_source = LabelSource.OFFICIAL_HARNESS

    assert content_hash(record) != before


def test_a_record_hashes_differently_under_a_different_predecessor() -> None:
    """This is what makes it a chain rather than a set of independent hashes."""
    record = _records(1)[0]

    assert content_hash(record, GENESIS) != content_hash(record, "a" * 64)


def test_an_untouched_chain_verifies() -> None:
    records = _records(4)

    verdict = verify_chain(records, build_chain(records))

    assert verdict.intact
    assert verdict.could_have_failed


def test_editing_a_record_after_the_fact_breaks_the_chain_at_that_point() -> None:
    records = _records(5)
    hashes = build_chain(records)

    records[2].resolved = True

    verdict = verify_chain(records, hashes)
    assert not verdict.intact
    assert verdict.first_broken_index == 2


def test_removing_a_record_is_detected() -> None:
    records = _records(4)
    hashes = build_chain(records)

    verdict = verify_chain(records[:3], hashes)

    assert not verdict.intact


def test_a_single_record_cannot_demonstrate_an_intact_chain_and_says_so() -> None:
    records = _records(1)

    verdict = verify_chain(records, build_chain(records))

    assert verdict.intact
    assert not verdict.could_have_failed
    assert "too few" in verdict.summary()


def test_an_empty_chain_is_inconclusive_rather_than_intact() -> None:
    verdict = verify_chain([], [])

    assert not verdict.could_have_failed
