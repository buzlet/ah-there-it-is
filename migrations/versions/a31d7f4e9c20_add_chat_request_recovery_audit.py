"""add chat request recovery audit

Revision ID: a31d7f4e9c20
Revises: f19b2c4d6e81
Create Date: 2026-09-23 09:25:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a31d7f4e9c20"
down_revision: Union[str, Sequence[str], None] = "f19b2c4d6e81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("chat_requests") as batch:
        batch.add_column(sa.Column("recovered_from_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("recovery_note", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_chat_requests_recovered_from_id_chat_requests",
            "chat_requests",
            ["recovered_from_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_chat_requests_recovered_from_id",
            ["recovered_from_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_requests") as batch:
        batch.drop_index("ix_chat_requests_recovered_from_id")
        batch.drop_constraint(
            "fk_chat_requests_recovered_from_id_chat_requests",
            type_="foreignkey",
        )
        batch.drop_column("recovery_note")
        batch.drop_column("recovered_from_id")
