"""add chat request idempotency records

Revision ID: f19b2c4d6e81
Revises: cd2ab808e0c6
Create Date: 2026-09-23 08:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f19b2c4d6e81"
down_revision: Union[str, Sequence[str], None] = "cd2ab808e0c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("requested_conversation_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_chat_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_run_logs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_requests_request_key"),
        "chat_requests",
        ["request_key"],
        unique=True,
    )
    op.create_index(
        op.f("ix_chat_requests_status"),
        "chat_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_chat_requests_agent_run_id"),
        "chat_requests",
        ["agent_run_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_chat_requests_agent_run_id"),
        table_name="chat_requests",
    )
    op.drop_index(
        op.f("ix_chat_requests_status"),
        table_name="chat_requests",
    )
    op.drop_index(
        op.f("ix_chat_requests_request_key"),
        table_name="chat_requests",
    )
    op.drop_table("chat_requests")
