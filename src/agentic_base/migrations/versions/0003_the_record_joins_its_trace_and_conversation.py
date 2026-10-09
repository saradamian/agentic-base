"""the record joins its trace and its conversation, and says how the model was asked

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09 10:00:00.000000

Adds trace_id, conversation_id, sampling, finish_reasons and the two cache token counts. Existing
rows get each field's default, which is what the integrity check expects of a field their audit
entries predate. No entry is rewritten.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEXT = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    with op.batch_alter_table("run_record", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("trace_id", _TEXT, nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column("conversation_id", _TEXT, nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "sampling", sa.JSON(), nullable=True, server_default=sa.text("'{}'")
            )
        )
        batch_op.add_column(
            sa.Column(
                "finish_reasons",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "cache_read_tokens", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column(
                "cache_creation_tokens",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_index(
            batch_op.f("ix_run_record_trace_id"), ["trace_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_run_record_conversation_id"),
            ["conversation_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("run_record", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_run_record_conversation_id"))
        batch_op.drop_index(batch_op.f("ix_run_record_trace_id"))
        for column in (
            "cache_creation_tokens",
            "cache_read_tokens",
            "finish_reasons",
            "sampling",
            "conversation_id",
            "trace_id",
        ):
            batch_op.drop_column(column)
