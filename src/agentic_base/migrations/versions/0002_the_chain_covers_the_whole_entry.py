"""the chain covers the whole entry and anchors its head

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26 09:31:54.653854

Besides the schema, this rewrites every existing tenant's chain into the entry scheme: each
entry gains its position and the digests of the personal fields, its personal snapshot values
(principal, approvals) leave the log for good, every hash is recomputed, one ``migrated`` entry
per run records the row as it stands, and the tenant's head is anchored. The rewrite is the
service's own, done once, under a migration the version table names; it is not undone by the
downgrade, so a downgraded log does not verify under the old scheme.

A rewrite recomputes every hash, so it would turn a log that had been tampered with into one
that verifies. Before anything changes, each tenant's log is therefore verified under the 0001
scheme it was written in: the chain must recompute, and every chained run must equal its latest
entry. A tenant that fails stops the upgrade before any schema change, naming what failed. An
operator who has examined the damage can let the upgrade proceed by naming the tenant in
``MIGRATE_ACCEPT_UNVERIFIED`` (comma-separated, or ``*``); that tenant's ``migrated`` entries are
then written as ``migrated_unverified``, so the rewritten chain records that its history was
re-anchored over a log that did not verify.
"""

import enum
import hashlib
import json
import logging
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlmodel import Session, col, select

import agentic_base.domain.run_record
from agentic_base.domain.audit import AuditEntry, ChainHead
from agentic_base.domain.integrity import (
    GENESIS,
    digest_value,
    entry_hash,
    field_digests,
    snapshot,
)
from agentic_base.domain.run_record import RunRecord

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_log = logging.getLogger(__name__)

ACCEPT_UNVERIFIED = "MIGRATE_ACCEPT_UNVERIFIED"

# The 0001 scheme, frozen. The log is judged by the rules it was written under, not by whatever
# `domain.integrity` says today, so these copies must never follow later changes to that module.
_AUDIT_FIELDS_0001 = (
    "run_id",
    "created_at",
    "tenant",
    "item",
    "arm",
    "arm_fingerprint",
    "model",
    "endpoint",
    "precision",
    "code_revision",
    "status",
    "failure_kind",
    "resolved",
    "label_source",
    "degraded",
    "instrument",
    "principal",
    "classification",
    "isolation_tier",
    "redaction",
    "disclosure",
    "content_marking",
    "approvals",
)
_GENESIS_0001 = "0" * 64


def _canonical_0001(values: dict[str, Any]) -> bytes:
    return json.dumps(
        values, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _plain_0001(value: Any) -> Any:
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _snapshot_0001(values: Any) -> dict[str, Any]:
    """The 0001 snapshot of anything that maps field names to values."""
    plain = {field: _plain_0001(values.get(field)) for field in _AUDIT_FIELDS_0001}
    snapshot: dict[str, Any] = json.loads(_canonical_0001(plain))
    return snapshot


def _hash_0001(snapshot: dict[str, Any], previous: str) -> str:
    return hashlib.sha256(
        _canonical_0001({**snapshot, "previous_hash": previous})
    ).hexdigest()


def _failures_under_0001(connection: sa.Connection) -> dict[str, str]:
    """Each tenant whose log does not verify under the 0001 scheme, and why.

    Reads the 0001 tables through their 0001 columns only: the ORM models already carry the
    columns this migration adds, and a select through them fails before the schema changes.
    """
    entries = sa.table(
        "audit_entry",
        sa.column("seq", sa.Integer()),
        sa.column("tenant", sa.String()),
        sa.column("run_id", sa.String()),
        sa.column("audit_fields", sa.JSON()),
        sa.column("hash", sa.String()),
    )
    types: dict[str, Any] = {
        "created_at": agentic_base.domain.run_record.UTCDateTime(timezone=True),
        "resolved": sa.Boolean(),
        "degraded": sa.Boolean(),
        "approvals": sa.JSON(),
    }
    runs = sa.table(
        "run_record",
        *(sa.column(name, types.get(name, sa.String())) for name in _AUDIT_FIELDS_0001),
    )

    failures: dict[str, str] = {}
    log: dict[str, list[Any]] = {}
    for row in connection.execute(sa.select(entries).order_by(entries.c.seq)):
        log.setdefault(row.tenant, []).append(row)
    for tenant, tenant_entries in log.items():
        previous = _GENESIS_0001
        for index, entry in enumerate(tenant_entries):
            recomputed = _hash_0001(_snapshot_0001(entry.audit_fields or {}), previous)
            if recomputed != entry.hash:
                failures[tenant] = (
                    f"entry {index} (run {entry.run_id}, seq {entry.seq}) does not match "
                    "its recorded hash"
                )
                break
            previous = recomputed
    latest = {
        (entry.tenant, entry.run_id): entry.audit_fields or {}
        for tenant_entries in log.values()
        for entry in tenant_entries
    }
    altered: dict[str, list[str]] = {}
    for row in connection.execute(sa.select(runs)):
        fields = latest.get((row.tenant, row.run_id))
        if fields is not None and _snapshot_0001(row._mapping) != _snapshot_0001(
            fields
        ):
            altered.setdefault(row.tenant, []).append(row.run_id)
    for tenant, run_ids in altered.items():
        reason = f"run(s) {', '.join(sorted(run_ids))} differ from their latest entry"
        failures[tenant] = (
            f"{failures[tenant]}; {reason}" if tenant in failures else reason
        )
    return failures


def _accepted_unverified() -> set[str]:
    return {
        name.strip()
        for name in os.environ.get(ACCEPT_UNVERIFIED, "").split(",")
        if name.strip()
    }


def upgrade() -> None:
    failures = _failures_under_0001(op.get_bind())
    accepted = _accepted_unverified()
    refused = {
        tenant: why
        for tenant, why in failures.items()
        if tenant not in accepted and "*" not in accepted
    }
    if refused:
        lines = "\n".join(
            f"  {tenant}: {why}" for tenant, why in sorted(refused.items())
        )
        raise RuntimeError(
            "the audit log does not verify under the scheme it was written in, and rewriting "
            "it would make the damage verify:\n"
            f"{lines}\n"
            "Nothing was changed. Examine the log with 0.7.x's GET /runs/integrity. To proceed "
            f"anyway, name the tenants in {ACCEPT_UNVERIFIED}; their rewritten chains will say "
            "so in every migrated entry."
        )
    for tenant, why in sorted(failures.items()):
        _log.warning(
            "rewriting an unverified log for tenant %s, as accepted: %s", tenant, why
        )

    op.create_table(
        "audit_head",
        sa.Column("tenant", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("tenant"),
    )
    with op.batch_alter_table("audit_entry", schema=None) as batch_op:
        # Nullable until the rewrite below has numbered every existing entry.
        batch_op.add_column(sa.Column("chain_seq", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("digests", sa.JSON(), nullable=True))

    with op.batch_alter_table("run_record", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "erased_at",
                agentic_base.domain.run_record.UTCDateTime(timezone=True),
                nullable=True,
            )
        )

    _rewrite_chains(Session(bind=op.get_bind()), unverified=set(failures))

    with op.batch_alter_table("audit_entry", schema=None) as batch_op:
        batch_op.alter_column("chain_seq", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint(
            "uq_audit_entry_tenant_chain_seq", ["tenant", "chain_seq"]
        )


def _claims_completed_erasure(record: RunRecord) -> bool:
    """An honest pre-migration erasure claim: the marker, and none of what an erasure removes.

    A marker beside content is the forgery the old sweep honoured; it gets no stamp, so the
    next sweep erases the run like any other.
    """
    return bool(
        (record.extra or {}).get("erasure")
        and not record.system_prompt
        and not record.messages
        and not record.principal
        and not any(
            (approval or {}).get("by") or (approval or {}).get("note")
            for approval in record.approvals or []
        )
    )


def _claimed_at(record: RunRecord) -> datetime:
    marker = (record.extra or {}).get("erasure")
    claimed = marker.get("at") if isinstance(marker, dict) else None
    if isinstance(claimed, str):
        try:
            return datetime.fromisoformat(claimed)
        except ValueError:
            pass
    return record.created_at


def _rewrite_chains(session: Session, *, unverified: set[str]) -> None:
    tenants = set(session.exec(select(AuditEntry.tenant).distinct()).all()) | set(
        session.exec(select(RunRecord.tenant).distinct()).all()
    )
    for tenant in sorted(tenants):
        runs = list(
            session.exec(
                select(RunRecord)
                .where(RunRecord.tenant == tenant)
                .order_by(col(RunRecord.created_at), col(RunRecord.run_id))
            ).all()
        )
        for run in runs:
            if run.erased_at is None and _claims_completed_erasure(run):
                run.erased_at = _claimed_at(run)
                session.add(run)

        entries = list(
            session.exec(
                select(AuditEntry)
                .where(AuditEntry.tenant == tenant)
                .order_by(col(AuditEntry.seq))
            ).all()
        )
        previous = GENESIS
        position = 0
        for entry in entries:
            position += 1
            fields = dict(entry.audit_fields or {})
            digests = {
                name: digest_value(fields.pop(name))
                for name in ("principal", "approvals")
                if name in fields
            }
            entry.chain_seq = position
            entry.audit_fields = fields
            entry.digests = digests
            entry.previous_hash = previous
            entry.hash = entry_hash(
                position, entry.run_id, entry.event, entry.at, fields, digests, previous
            )
            previous = entry.hash
            session.add(entry)

        # One entry per already-chained run, so its latest snapshot carries the fields the
        # scheme now covers. A row that never had an entry stays unchained and stays flagged.
        chained = {entry.run_id for entry in entries}
        at = datetime.now(timezone.utc)
        event = "migrated_unverified" if tenant in unverified else "migrated"
        for run in runs:
            if run.run_id not in chained:
                continue
            position += 1
            fields, digests = snapshot(run), field_digests(run)
            entry = AuditEntry(
                tenant=tenant,
                run_id=run.run_id,
                event=event,
                at=at,
                chain_seq=position,
                audit_fields=fields,
                digests=digests,
                previous_hash=previous,
                hash=entry_hash(
                    position, run.run_id, event, at, fields, digests, previous
                ),
            )
            previous = entry.hash
            session.add(entry)

        if position:
            session.add(ChainHead(tenant=tenant, seq=position, hash=previous))
    session.flush()


def downgrade() -> None:
    with op.batch_alter_table("run_record", schema=None) as batch_op:
        batch_op.drop_column("erased_at")

    with op.batch_alter_table("audit_entry", schema=None) as batch_op:
        batch_op.drop_constraint("uq_audit_entry_tenant_chain_seq", type_="unique")
        batch_op.drop_column("digests")
        batch_op.drop_column("chain_seq")

    op.drop_table("audit_head")
