"""Add Telegram private-chat bindings and durable polling state."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2b8d5f1a4c20"
down_revision: Union[str, Sequence[str], None] = "1a7c4e9d2b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_chat_bindings",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("chat_id"),
        sa.UniqueConstraint("conversation_id", name="uq_telegram_binding_conversation"),
    )
    op.create_index(
        "ix_telegram_chat_bindings_conversation_id",
        "telegram_chat_bindings",
        ["conversation_id"],
        unique=False,
    )
    op.create_table(
        "telegram_polling_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("next_offset", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_telegram_polling_state_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("telegram_polling_state")
    op.drop_index(
        "ix_telegram_chat_bindings_conversation_id",
        table_name="telegram_chat_bindings",
    )
    op.drop_table("telegram_chat_bindings")
