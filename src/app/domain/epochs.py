"""Declaring that a commit changed what a field means.

A configuration fingerprint tells you two runs were configured the same way. It cannot tell you
that the code underneath that configuration changed meaning between them, and that is where the
expensive mistakes live. In the predecessor project every serious wound was a code change landing
in the middle of a corpus: an arm that ran with the mechanism its own label said was disabled, a
retrieval default flipping so that the same absent setting meant opposite things on either side,
a benchmark whose scoring changed under a stable name.

What saved or damaged us each time was whether someone had declared the boundary. So this is a
small table of declarations, and a classifier that puts a record before a boundary, after it, or
in the honest third state.

The third state matters more than the other two. A record whose code revision is unknown cannot
be placed, and guessing is how a corpus quietly mixes two things. Pooling across an unknown is
refused, not estimated.

This costs almost nothing today and cannot be added later, because a boundary cannot be declared
for records that never recorded which code produced them.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


class Epoch(str, enum.Enum):
    BEFORE = "before"
    AFTER = "after"
    UNKNOWN = "unknown"
    """The record cannot be placed. Not an error, and not poolable."""


class MeaningChange(SQLModel, table=True):
    """One declaration that a commit changed what something means."""

    __tablename__ = "meaning_change"

    commit: str = Field(primary_key=True, description="The commit at which the new meaning starts.")
    subject: str = Field(
        index=True,
        description="What changed meaning: a field name, a metric, an arm label, a scorer.",
    )
    description: str = Field(description="What it meant before, and what it means now.")
    effective_at: datetime = Field(
        description=(
            "When the commit landed. Used to place records whose own commit is not one we know "
            "about, which is most of them."
        )
    )
    declared_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    declared_by: str = Field(default="")


@dataclass(frozen=True)
class PoolVerdict:
    """Whether a set of records may be compared as one population."""

    poolable: bool
    subject: str
    counts: dict[Epoch, int]
    reason: str = ""

    @property
    def records_examined(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        if self.records_examined == 0:
            return f"inconclusive: no records examined for {self.subject!r}"
        if self.poolable:
            return f"poolable: {self.records_examined} records, all on one side of {self.subject!r}"
        return f"not poolable: {self.reason}"


def classify(record, change: MeaningChange) -> Epoch:
    """Place one record relative to one declared boundary.

    A record whose own revision is the declaring commit is on the new side, because the commit is
    the first to carry the new meaning.
    """
    revision = getattr(record, "code_revision", "") or ""
    if revision and revision == change.commit:
        return Epoch.AFTER

    created = getattr(record, "created_at", None)
    if created is None or change.effective_at is None:
        return Epoch.UNKNOWN

    # A record with no recorded revision can still be placed by time, but only if we accept that
    # a rebuilt or backfilled record may carry a misleading timestamp. Say so at the call site.
    if not revision:
        return Epoch.UNKNOWN

    left = created if created.tzinfo else created.replace(tzinfo=UTC)
    right = change.effective_at if change.effective_at.tzinfo else change.effective_at.replace(tzinfo=UTC)
    return Epoch.AFTER if left >= right else Epoch.BEFORE


def classify_all(records: Iterable, change: MeaningChange) -> dict[Epoch, int]:
    """Count how a set of records falls either side of a boundary."""
    counts = {Epoch.BEFORE: 0, Epoch.AFTER: 0, Epoch.UNKNOWN: 0}
    for record in records:
        counts[classify(record, change)] += 1
    return counts


def check_poolable(records: Sequence, change: MeaningChange) -> PoolVerdict:
    """Whether these records may be treated as one population across this boundary.

    Refused when they straddle the boundary, and refused when any record cannot be placed. The
    second refusal is the one that feels excessive and is the one that pays: an unplaceable record
    is exactly the case where a guess is invisible afterwards.
    """
    counts = classify_all(records, change)
    if counts[Epoch.UNKNOWN]:
        return PoolVerdict(
            poolable=False,
            subject=change.subject,
            counts=counts,
            reason=(
                f"{counts[Epoch.UNKNOWN]} record(s) carry no usable code revision, so they cannot "
                f"be placed relative to {change.commit}"
            ),
        )
    if counts[Epoch.BEFORE] and counts[Epoch.AFTER]:
        return PoolVerdict(
            poolable=False,
            subject=change.subject,
            counts=counts,
            reason=(
                f"records straddle {change.commit}: {counts[Epoch.BEFORE]} before and "
                f"{counts[Epoch.AFTER]} after, where {change.subject!r} changed meaning"
            ),
        )
    return PoolVerdict(poolable=True, subject=change.subject, counts=counts)
