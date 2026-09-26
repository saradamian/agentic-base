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
"""

from collections.abc import Sequence
from datetime import datetime, timezone

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


def upgrade() -> None:
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

    _rewrite_chains(Session(bind=op.get_bind()))

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


def _rewrite_chains(session: Session) -> None:
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
        for run in runs:
            if run.run_id not in chained:
                continue
            position += 1
            fields, digests = snapshot(run), field_digests(run)
            entry = AuditEntry(
                tenant=tenant,
                run_id=run.run_id,
                event="migrated",
                at=at,
                chain_seq=position,
                audit_fields=fields,
                digests=digests,
                previous_hash=previous,
                hash=entry_hash(
                    position, run.run_id, "migrated", at, fields, digests, previous
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
