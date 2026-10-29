"""the log names who made each change

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29 14:00:00.000000

Adds ``actor`` to the audit entry. Existing entries get the empty string, which the entry hash
leaves out, so every entry written before this revision still verifies. No entry is rewritten.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEXT = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    with op.batch_alter_table("audit_entry", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("actor", _TEXT, nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_entry", schema=None) as batch_op:
        batch_op.drop_column("actor")
