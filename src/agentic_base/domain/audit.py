"""The audit log: one chained entry for every change to a run's audit fields.

A record's outcome is attached after it is written and approvals are added later still, so one
hash per record taken at creation would break on every legitimate label. Instead each write
appends an entry holding a snapshot of the audit fields at that moment, chained to the tenant's
previous entry. Verification checks two things: that the chain of entries recomputes, which
catches an entry edited or removed, and that each run's current fields equal its latest
snapshot, which catches a record edited without going through the service.

A unique constraint on the tenant and the previous hash makes a fork impossible: two writers
that read the same predecessor cannot both append to it, and the second is told to retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, Session, SQLModel, col, select

from agentic_base.domain.integrity import (
    GENESIS,
    ChainVerdict,
    hash_snapshot,
    snapshot,
    verify_chain,
)
from agentic_base.domain.run_record import RunRecord, UTCDateTime


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEntry(SQLModel, table=True):  # type: ignore[call-arg]
    """One change to one run, chained to the previous change for the same tenant."""

    __tablename__ = "audit_entry"
    __table_args__ = (UniqueConstraint("tenant", "previous_hash"),)

    seq: int | None = Field(default=None, primary_key=True)
    tenant: str = Field(index=True)
    run_id: str = Field(index=True)
    event: str
    at: datetime = Field(
        default_factory=_now, sa_column=Column(UTCDateTime, nullable=False)
    )
    audit_fields: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    previous_hash: str
    hash: str


def append(session: Session, record: RunRecord, event: str) -> AuditEntry:
    """Add the entry for a change to *record*. The caller commits both in one transaction."""
    last = session.exec(
        select(AuditEntry)
        .where(AuditEntry.tenant == record.tenant)
        .order_by(col(AuditEntry.seq).desc())
        .limit(1)
    ).first()
    previous = last.hash if last is not None else GENESIS
    values = snapshot(record)
    entry = AuditEntry(
        tenant=record.tenant,
        run_id=record.run_id,
        event=event,
        audit_fields=values,
        previous_hash=previous,
        hash=hash_snapshot(values, previous),
    )
    session.add(entry)
    return entry


@dataclass(frozen=True)
class AuditVerdict:
    """The chain's verdict, and what comparing each run to its latest entry found."""

    chain: ChainVerdict
    runs_checked: int
    unchained: list[str] = field(default_factory=list)
    altered: list[str] = field(default_factory=list)

    @property
    def intact(self) -> bool:
        return self.chain.intact and not self.unchained and not self.altered

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
        if self.altered:
            problems.append(f"{len(self.altered)} run(s) differ from their last entry")
        if self.unchained:
            problems.append(f"{len(self.unchained)} run(s) have no entry at all")
        if problems:
            return "; ".join(problems)
        return f"intact: {self.runs_checked} runs match {self.chain.records_checked} entries"


def verify(session: Session, tenant: str) -> AuditVerdict:
    """Recompute a tenant's log and compare every run to its latest entry."""
    entries = session.exec(
        select(AuditEntry)
        .where(AuditEntry.tenant == tenant)
        .order_by(col(AuditEntry.seq))
    ).all()
    chain = verify_chain(
        [SimpleNamespace(**e.audit_fields) for e in entries], [e.hash for e in entries]
    )
    latest = {e.run_id: e.audit_fields for e in entries}
    records = session.exec(select(RunRecord).where(RunRecord.tenant == tenant)).all()
    unchained = sorted(r.run_id for r in records if r.run_id not in latest)
    altered = sorted(
        r.run_id
        for r in records
        if r.run_id in latest and snapshot(r) != latest[r.run_id]
    )
    return AuditVerdict(
        chain=chain, runs_checked=len(records), unchained=unchained, altered=altered
    )
