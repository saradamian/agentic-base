"""Keeping a record long enough, and keeping no more of it than is needed.

Two regimes pull in opposite directions and this module is where they meet. The AI Act asks a
provider of a high-risk system to keep the logs its system generates for at least six months.
The GDPR asks for data minimisation and gives a person the right to have their personal data
erased. A platform that reads only one of them either destroys its own evidence or keeps
transcripts forever.

They are reconcilable because they ask for different things. What an audit turns on is what ran,
under what configuration, what was decided and who decided it: that is exactly the set the hash
chain covers, and none of it is personal. The personal data is in the transcript, which the chain
deliberately does not cover. So a transcript can be erased on request, or on a schedule, and the
record it belonged to stays verifiable and countable: the run still happened, its outcome still
stands, and the chain still checks.

Two rules follow, and both are refusals rather than defaults.

A policy shorter than the floor is refused, not clamped. A configuration that quietly kept less
than the law requires would be indistinguishable from one that meant to.

An erasure says so on the record. `extra["erasure"]` names when it happened, why, and which
fields were emptied, so a reader can tell an erased transcript from a run that never had one.
This is the same rule as the redaction instrument: a record states what was done to it.

Scheduling is the platform's, not this module's. What lives here is the decision of which records
are due and what erasing one means.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from agentic_base.domain.outcomes import RunRecordCreate

FLOOR_DAYS = 183
"""Six months, the AI Act's log-retention floor, as whole days.

Article 19 asks providers of high-risk systems to keep automatically generated logs for at least
six months. Six months is not a fixed number of days; 183 is the longest half-year, so a policy
that clears this clears the requirement whichever half-year it lands in.
"""

ERASABLE_FIELDS = ("system_prompt", "messages")
"""What an erasure empties: the transcript, and only the transcript.

Everything the hash chain covers is left alone, which is what lets an erased record stay evidence.
"""


@dataclass(frozen=True)
class RetentionPolicy:
    """How long a tenant's transcripts are kept."""

    keep_days: int
    floor_days: int = FLOOR_DAYS

    def __post_init__(self) -> None:
        if self.keep_days < self.floor_days:
            raise ValueError(
                f"a retention policy of {self.keep_days} days is below the {self.floor_days}-day "
                "floor the AI Act sets for keeping a high-risk system's logs. Raise the policy, "
                "or lower the floor deliberately and say why"
            )

    def cutoff(self, now: datetime) -> datetime:
        """Records created before this are due."""
        return now - timedelta(days=self.keep_days)


@dataclass(frozen=True)
class RetentionSweep:
    """What a sweep looked at and what it found.

    The count of records examined is part of the result, so no findings reads as no findings
    rather than as a sweep that could not see anything.
    """

    examined: int
    due: tuple[Any, ...]
    cutoff: datetime
    policy: RetentionPolicy

    @property
    def count(self) -> int:
        return len(self.due)


def plan(
    records: Sequence[Any], now: datetime, policy: RetentionPolicy
) -> RetentionSweep:
    """Which records have transcripts older than the policy allows.

    A record with no creation time is never due: unplaceable is not the same as old, and the
    failure of a sweep to read a timestamp must not delete anything.
    """
    cutoff = policy.cutoff(now)
    due = tuple(
        record
        for record in records
        if isinstance(getattr(record, "created_at", None), datetime)
        and record.created_at < cutoff
    )
    return RetentionSweep(examined=len(records), due=due, cutoff=cutoff, policy=policy)


def erase(payload: RunRecordCreate, at: datetime, reason: str) -> RunRecordCreate:
    """Empty the transcript and record that it was emptied.

    The record stays countable and verifiable: everything the hash chain covers is untouched, so
    an erasure does not break the chain and cannot be mistaken for one.
    """
    if not reason.strip():
        raise ValueError("an erasure records why it happened")
    already = payload.extra.get("erasure")
    if already:
        return payload
    return payload.model_copy(
        update={
            "system_prompt": "",
            "messages": [],
            "extra": {
                **payload.extra,
                "erasure": {
                    "at": at.isoformat(),
                    "reason": reason,
                    "fields": list(ERASABLE_FIELDS),
                },
            },
        }
    )


def was_erased(payload: RunRecordCreate) -> bool:
    """Whether this record's transcript was erased, as opposed to never having had one."""
    return bool(payload.extra.get("erasure"))
