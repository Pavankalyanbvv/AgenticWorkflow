"""Initial tables: conversations, messages, agent_runs.

Revision ID: 0001
Revises:
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(64)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_type", sa.String(100)),
        sa.Column("provider", sa.String(64)),
        sa.Column("model", sa.String(128)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("trace_id", sa.String(64)),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_status",
        ),
    )
    op.create_index(
        "ix_agent_runs_conversation_started", "agent_runs", ["conversation_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_conversation_started", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
