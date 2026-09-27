"""add durable Telegram failure notice markers

Revision ID: 9c7d21b4f630
Revises: 2b8d5f1a4c20
Create Date: 2026-09-27 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c7d21b4f630"
down_revision: Union[str, Sequence[str], None] = "2b8d5f1a4c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_failure_notices",
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("notice_kind", sa.String(length=20), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "notice_kind IN ('no_mutation', 'uncertain')",
            name="ck_telegram_failure_notices_kind",
        ),
        sa.PrimaryKeyConstraint("update_id"),
        sa.UniqueConstraint(
            "request_key", name="uq_telegram_failure_notices_request_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_failure_notices")
