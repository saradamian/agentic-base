"""Keeping a record long enough, and erasing no more of it than the transcript."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from agentic_base.domain.integrity import content_hash
from agentic_base.domain.outcomes import RunRecordCreate
from agentic_base.domain.retention import (
    FLOOR_DAYS,
    RetentionPolicy,
    erase,
    plan,
    was_erased,
)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


@dataclass
class _Row:
    created_at: datetime | None
    run_id: str = "r1"


def _payload(**kwargs) -> RunRecordCreate:
    body = {
        "tenant": "hpml",
        "code_revision": "abc1234",
        "system_prompt": "you are an agent working for Maria Jansen",
        "messages": [{"role": "user", "content": "mail maria@example.org"}],
    }
    body.update(kwargs)
    return RunRecordCreate(**body)


def test_a_policy_below_the_six_month_floor_is_refused() -> None:
    """Clamping would be indistinguishable from a configuration that meant to keep less."""
    with pytest.raises(ValueError, match="floor"):
        RetentionPolicy(keep_days=30)

    assert RetentionPolicy(keep_days=FLOOR_DAYS).keep_days == FLOOR_DAYS
    assert RetentionPolicy(keep_days=30, floor_days=30).keep_days == 30


def test_a_sweep_reports_what_it_examined_beside_what_is_due() -> None:
    policy = RetentionPolicy(keep_days=200)
    rows = [
        _Row(NOW - timedelta(days=365)),
        _Row(NOW - timedelta(days=10)),
        _Row(NOW - timedelta(days=201)),
    ]

    sweep = plan(rows, NOW, policy)

    assert sweep.examined == 3
    assert sweep.count == 2
    assert sweep.cutoff == NOW - timedelta(days=200)


def test_a_record_with_no_timestamp_is_never_due() -> None:
    """Unplaceable is not old, and a sweep that cannot read a date must not delete."""
    sweep = plan([_Row(None)], NOW, RetentionPolicy(keep_days=200))

    assert sweep.examined == 1 and sweep.count == 0


def test_erasing_empties_the_transcript_and_says_so() -> None:
    erased = erase(_payload(), NOW, "the person asked")

    assert erased.system_prompt == "" and erased.messages == []
    assert erased.extra["erasure"] == {
        "at": NOW.isoformat(),
        "reason": "the person asked",
        "fields": ["system_prompt", "messages"],
    }
    assert was_erased(erased) and not was_erased(_payload())


def test_erasing_leaves_the_chain_intact() -> None:
    """The hash covers what an audit turns on, and the transcript is not in it. That is what
    lets a person's data go while the evidence that the run happened stays."""
    before = _payload(item="task-1", arm="baseline")

    after = erase(before, NOW, "the person asked")

    assert content_hash(after) == content_hash(before)


def test_erasing_twice_keeps_the_first_record_of_it() -> None:
    once = erase(_payload(), NOW, "the person asked")

    twice = erase(once, NOW + timedelta(days=1), "a sweep")

    assert twice.extra["erasure"]["reason"] == "the person asked"


def test_an_erasure_records_why() -> None:
    with pytest.raises(ValueError, match="why"):
        erase(_payload(), NOW, "  ")
