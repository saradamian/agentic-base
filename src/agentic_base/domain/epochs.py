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

Two kinds of declaration live here, because code changes underneath a run in two ways.

* An application's own code changes at a commit. :class:`MeaningChange` declares that boundary, and
  records are placed before or after it by their revision.
* A library the application imports changes at a release. :class:`VersionEpochs` declares which
  recorded versions are equivalent, and refuses to pool any version nobody declared. A boundary
  would be the wrong shape for this: every release after it would join the new side unreviewed,
  and the runs recorded before versions were written could never be placed. The equivalence
  sets are agentic-env's, proven on its campaign ledger before they moved here.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Epoch(str, enum.Enum):
    BEFORE = "before"
    AFTER = "after"
    UNKNOWN = "unknown"
    """The record cannot be placed. Not an error, and not poolable."""


class MeaningChange(BaseModel):
    """One declaration that a commit changed what something means.

    A plain model rather than a table. Applying a boundary is what every consumer needs;
    storing one is what this service happens to do, and a consumer that imports the classifier
    must not thereby acquire a database driver.
    """

    commit: str = Field(description="The commit at which the new meaning starts.")
    subject: str = Field(
        description="What changed meaning: a field name, a metric, an arm label, a scorer.",
    )
    description: str = Field(description="What it meant before, and what it means now.")
    effective_at: datetime = Field(
        description=(
            "When the commit landed. Used to place records whose own commit is not one we know "
            "about, which is most of them."
        )
    )
    declared_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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
    the first to carry the new meaning. A change in an imported library is not declared here; see
    :class:`VersionEpochs`.
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

    record_at = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    boundary_at = (
        change.effective_at
        if change.effective_at.tzinfo
        else change.effective_at.replace(tzinfo=timezone.utc)
    )
    return Epoch.AFTER if record_at >= boundary_at else Epoch.BEFORE


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


def version_key(versions: Mapping[str, str] | None) -> str:
    """One string per distinct set of component versions; ``""`` for a run that recorded none."""
    return ",".join(
        f"{name}={value}" for name, value in sorted((versions or {}).items())
    )


@dataclass(frozen=True)
class VersionVerdict:
    """Whether runs recorded against these component versions may be compared as one population."""

    poolable: bool
    keys_examined: int
    undeclared: tuple[str, ...] = ()
    epochs_spanned: int = 0
    reason: str = ""

    @property
    def could_have_failed(self) -> bool:
        """False when no version was examined, so a clean verdict says nothing."""
        return self.keys_examined > 0

    def summary(self) -> str:
        if not self.could_have_failed:
            return "inconclusive: no component versions examined"
        if self.poolable:
            return f"poolable: {self.keys_examined} version set(s), one declared epoch"
        return f"not poolable: {self.reason}"


@dataclass(frozen=True)
class VersionEpochs:
    """Sets of component versions declared equivalent for pooling.

    Each set holds :func:`version_key` values. ``""``, a run recorded before versions were written,
    belongs to an epoch only when a set names it, which is how a corpus that predates recording is
    declared equivalent to the first versions recorded after it. Runs may pool when every key they
    carry is declared and all fall in one set. A version nobody declared is refused, however close
    it is to one that was: extending a set is a reviewed statement that a release did not change
    what the runs measure, and it is made with its reason beside it.
    """

    epochs: tuple[frozenset[str], ...] = field(default_factory=tuple)

    def epoch_of(self, key: str) -> int | None:
        """The index of the set a key belongs to, or None when no set declares it."""
        for index, epoch in enumerate(self.epochs):
            if key in epoch:
                return index
        return None

    def check(self, keys: Iterable[str]) -> VersionVerdict:
        """Whether runs carrying these version keys may pool."""
        distinct = sorted(set(keys))
        undeclared = tuple(k for k in distinct if self.epoch_of(k) is None)
        if undeclared:
            shown = ", ".join(repr(k) for k in undeclared)
            return VersionVerdict(
                poolable=False,
                keys_examined=len(distinct),
                undeclared=undeclared,
                reason=f"no declared epoch names {shown}; declare one, with the reason",
            )
        spanned = len({self.epoch_of(k) for k in distinct})
        if spanned > 1:
            return VersionVerdict(
                poolable=False,
                keys_examined=len(distinct),
                epochs_spanned=spanned,
                reason=f"the versions span {spanned} declared epochs; split the comparison",
            )
        return VersionVerdict(
            poolable=True, keys_examined=len(distinct), epochs_spanned=spanned
        )

    def check_records(self, records: Iterable[object]) -> VersionVerdict:
        """The same, reading ``component_versions`` from each record."""
        return self.check(
            version_key(getattr(record, "component_versions", None))
            for record in records
        )
