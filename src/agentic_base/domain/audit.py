"""The audit log: one chained entry for every change to a run's audit fields.

A record's outcome is attached after it is written and approvals are added later still, so one
hash per record taken at creation would break on every legitimate label. Instead each write
appends an entry holding a snapshot of the audit fields at that moment — and a digest of every
personal or bulk field, never the value — chained to the tenant's previous entry and carrying
its position in that chain. The tenant's head entry is recorded in ``audit_head`` in the same
transaction.

Verification checks four things: that the chain of entries recomputes in sequence, which
catches an entry edited, forged, reordered or removed; that the recorded head is the last
entry, which catches a truncated tail; that each run's current fields and digests equal its
latest snapshot, which catches a record edited without going through the service; and that
runs and entries cover each other, which catches a removed run row as well as a smuggled one.
A run whose personal fields were erased is reported as erased, not as tampered: the digests of
the erased content are still in the log, the content is not, and the chain stays intact.

A unique constraint on the tenant and the previous hash makes a fork impossible: two writers
that read the same predecessor cannot both append to it, and the second is told to retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, Session, SQLModel, col, select

from agentic_base.domain.integrity import (
    GENESIS,
    ChainVerdict,
    entry_hash,
    field_digests,
    snapshot,
)
from agentic_base.domain.run_record import RunRecord, UTCDateTime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEntry(SQLModel, table=True):  # type: ignore[call-arg]
    """One change to one run, chained to the previous change for the same tenant."""

    __tablename__ = "audit_entry"
    __table_args__ = (
        UniqueConstraint("tenant", "previous_hash"),
        # Named, because the migration adds it to an existing table and a batch operation
        # cannot drop what it cannot name.
        UniqueConstraint("tenant", "chain_seq", name="uq_audit_entry_tenant_chain_seq"),
    )

    seq: int | None = Field(default=None, primary_key=True)
    tenant: str = Field(index=True)
    run_id: str = Field(index=True)
    event: str
    at: datetime = Field(
        default_factory=_now, sa_column=Column(UTCDateTime, nullable=False)
    )
    chain_seq: int
    """Position in the tenant's chain, starting at 1. Hashed, so a gap has a place and a name."""
    audit_fields: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    digests: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    """SHA-256 per personal or bulk field. The log covers them without holding them."""
    previous_hash: str
    hash: str


class ChainHead(SQLModel, table=True):  # type: ignore[call-arg]
    """Where each tenant's chain ends, written in the same transaction as every append.

    Without it, deleting the last entries leaves a shorter chain that still recomputes. With
    it, the cut is named: the head points past the end of the log. Rewriting the head as well
    is the whole-chain rewrite this mechanism does not claim to resist.
    """

    __tablename__ = "audit_head"

    tenant: str = Field(primary_key=True)
    seq: int
    hash: str


def append(session: Session, record: RunRecord, event: str) -> AuditEntry:
    """Add the entry for a change to *record* and move the tenant's head to it.

    The caller commits both in one transaction.
    """
    last = session.exec(
        select(AuditEntry)
        .where(AuditEntry.tenant == record.tenant)
        .order_by(col(AuditEntry.seq).desc())
        .limit(1)
    ).first()
    previous = last.hash if last is not None else GENESIS
    chain_seq = (last.chain_seq if last is not None else 0) + 1
    values = snapshot(record)
    digests = field_digests(record)
    at = _now()
    entry = AuditEntry(
        tenant=record.tenant,
        run_id=record.run_id,
        event=event,
        at=at,
        chain_seq=chain_seq,
        audit_fields=values,
        digests=digests,
        previous_hash=previous,
        hash=entry_hash(chain_seq, record.run_id, event, at, values, digests, previous),
    )
    session.add(entry)
    head = session.get(ChainHead, record.tenant)
    if head is None:
        head = ChainHead(tenant=record.tenant, seq=chain_seq, hash=entry.hash)
    else:
        head.seq, head.hash = chain_seq, entry.hash
    session.add(head)
    return entry


@dataclass(frozen=True)
class AuditVerdict:
    """The chain's verdict, and what comparing the log against the run rows found."""

    chain: ChainVerdict
    runs_checked: int
    head_seq: int | None = None
    """The head the service recorded for this tenant; None when it never wrote one."""
    unchained: list[str] = field(default_factory=list)
    altered: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)
    """Runs the log describes whose row is gone."""
    truncated: str = ""
    """Why the recorded head disagrees with the log; empty when it agrees."""
    erased: list[str] = field(default_factory=list)
    """Runs whose personal fields the service erased. Reported, not a failure."""

    @property
    def intact(self) -> bool:
        return (
            self.chain.intact
            and not self.unchained
            and not self.altered
            and not self.orphaned
            and not self.truncated
        )

    @property
    def could_have_failed(self) -> bool:
        """False for a tenant with no runs, where nothing was there to find altered."""
        return self.runs_checked >= 1

    def summary(self) -> str:
        if not self.could_have_failed:
            return "inconclusive: no runs recorded for this tenant"
        problems = []
        if not self.chain.intact:
            problems.append(
                f"the log is broken at entry {self.chain.first_broken_index}: "
                f"{self.chain.detail}"
            )
        if self.truncated:
            problems.append(self.truncated)
        if self.altered:
            problems.append(f"{len(self.altered)} run(s) differ from their last entry")
        if self.unchained:
            problems.append(f"{len(self.unchained)} run(s) have no entry at all")
        if self.orphaned:
            problems.append(
                f"{len(self.orphaned)} run(s) in the log no longer have a row"
            )
        if problems:
            return "; ".join(problems)
        base = f"intact: {self.runs_checked} runs match {self.chain.records_checked} entries"
        if self.erased:
            base += f", {len(self.erased)} erased"
        return base


def _recompute(entries: list[AuditEntry]) -> ChainVerdict:
    """Recompute a tenant's entries in sequence and report the first place they diverge."""
    previous = GENESIS
    for index, entry in enumerate(entries):
        detail = ""
        if entry.chain_seq != index + 1:
            detail = f"entry carries position {entry.chain_seq} where {index + 1} was expected"
        elif (
            entry_hash(
                entry.chain_seq,
                entry.run_id,
                entry.event,
                entry.at,
                entry.audit_fields,
                entry.digests,
                previous,
            )
            != entry.hash
        ):
            detail = "entry content does not match its recorded hash"
        if detail:
            return ChainVerdict(
                intact=False,
                records_checked=len(entries),
                first_broken_index=index,
                detail=detail,
            )
        previous = entry.hash
    return ChainVerdict(intact=True, records_checked=len(entries))


def verify(session: Session, tenant: str) -> AuditVerdict:
    """Recompute a tenant's log and compare it, both ways, against the run rows."""
    entries = list(
        session.exec(
            select(AuditEntry)
            .where(AuditEntry.tenant == tenant)
            .order_by(col(AuditEntry.chain_seq), col(AuditEntry.seq))
        ).all()
    )
    chain = _recompute(entries)

    head = session.get(ChainHead, tenant)
    last_seq = entries[-1].chain_seq if entries else 0
    last_hash = entries[-1].hash if entries else GENESIS
    truncated = ""
    if head is None and entries:
        truncated = "the log has entries but no recorded head"
    elif head is not None and (head.seq != last_seq or head.hash != last_hash):
        truncated = (
            f"the recorded head is entry {head.seq}, but the log ends at {last_seq}"
            if head.seq != last_seq
            else f"the log ends at entry {last_seq}, which is not the recorded head"
        )

    latest: dict[str, AuditEntry] = {e.run_id: e for e in entries}
    records = session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all()
    present = {r.run_id for r in records}
    unchained = sorted(r.run_id for r in records if r.run_id not in latest)
    altered = sorted(
        r.run_id
        for r in records
        if r.run_id in latest
        and (
            snapshot(r) != latest[r.run_id].audit_fields
            or field_digests(r) != latest[r.run_id].digests
        )
    )
    orphaned = sorted(set(latest) - present)
    erased = sorted(r.run_id for r in records if r.erased_at is not None)
    return AuditVerdict(
        chain=chain,
        runs_checked=len(records),
        head_seq=head.seq if head is not None else None,
        unchained=unchained,
        altered=altered,
        orphaned=orphaned,
        truncated=truncated,
        erased=erased,
    )
