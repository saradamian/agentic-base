"""Keeping a record long enough, and keeping no more of it than is needed.

Two regimes pull in opposite directions and this module is where they meet. The AI Act asks a
provider of a high-risk system to keep the logs its system generates for at least six months.
The GDPR asks for data minimisation and gives a person the right to have their personal data
erased. A platform that reads only one of them either destroys its own evidence or keeps
transcripts forever.

They are reconcilable because they ask for different things. What an audit turns on is what ran,
under what configuration, what was decided and who decided it. The personal part of that — the
transcript, the person the run acted for, the names of the people who approved — enters the
audit log only as digests (:data:`agentic_base.domain.integrity.DIGEST_FIELDS`), never as
values. So a person's data can be erased on request, or a transcript on a schedule, and the
record it belonged to stays verifiable and countable: the run still happened, its outcome still
stands, the chain still checks, and the verification reports the erasure instead of hiding it.

Two rules follow, and both are refusals rather than defaults.

A policy shorter than the floor is refused, not clamped. A configuration that quietly kept less
than the law requires would be indistinguishable from one that meant to.

An erasure says so on the record. `extra["erasure"]` names when it happened, why, and which
fields were emptied, so a reader can tell an erased transcript from a run that never had one.
That statement is for readers; the sweep's exemption is the server-set ``erased_at`` column,
because a writer-settable field that exempts a run from retention exempts it forever.

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

ERASABLE_FIELDS = ("system_prompt", "messages", "principal", "approvals")
"""What an erasure empties: the transcript, the person the run acted for, and the identities
inside each approval. The approvals keep their action, decision and time — that a person said
yes remains evidence; who no longer does. Everything the chain hashes as a value is left alone,
and what it hashes as a digest survives erasure by construction, which is what lets an erased
record stay evidence.
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
    """Empty the personal fields and record that they were emptied.

    The record stays countable and verifiable: everything the chain hashes as a value is
    untouched, and the erased fields live in the chain as digests, so an erasure does not
    break it and cannot be mistaken for one.
    """
    if not reason.strip():
        raise ValueError("an erasure records why it happened")
    if was_erased(payload) and not _carries_what_erasure_removes(payload):
        # A completed erasure keeps its first record. A marker beside content is a claim,
        # not an erasure, and does not stop this one.
        return payload
    return payload.model_copy(
        update={
            "system_prompt": "",
            "messages": [],
            "principal": "",
            "approvals": [
                approval.model_copy(update={"by": "", "note": ""})
                for approval in payload.approvals
            ],
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


def _carries_what_erasure_removes(payload: RunRecordCreate) -> bool:
    return bool(
        payload.system_prompt
        or payload.messages
        or payload.principal
        or any(approval.by or approval.note for approval in payload.approvals)
    )


def was_erased(payload: RunRecordCreate) -> bool:
    """Whether this record's payload claims an erasure, as opposed to never having had one.

    A statement for readers and for replayed exports. The retention sweep does not read it —
    its exemption is the server-set ``erased_at`` column on the stored row.
    """
    return bool(payload.extra.get("erasure"))


def accept_claimed_erasure(payload: RunRecordCreate) -> datetime | None:
    """Validate a payload that arrives already claiming an erasure, as a replayed export does.

    The claim is acceptable only when the record carries none of what an erasure removes;
    a claim beside content is a run trying to keep its transcript and skip retention, and it
    is refused. Returns the claimed time when the marker states a readable one, else None,
    and the caller records its own.
    """
    if not was_erased(payload):
        return None
    if _carries_what_erasure_removes(payload):
        raise ValueError(
            "the record claims an erasure but still carries what an erasure removes; "
            "extra['erasure'] is written by the service when it erases, not by a writer"
        )
    marker = payload.extra.get("erasure")
    claimed = marker.get("at") if isinstance(marker, dict) else None
    if isinstance(claimed, str):
        try:
            return datetime.fromisoformat(claimed)
        except ValueError:
            return None
    return None
