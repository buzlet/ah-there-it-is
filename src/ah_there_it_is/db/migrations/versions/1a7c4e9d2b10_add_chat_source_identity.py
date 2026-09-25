"""Add optional audit source identity to chat requests."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a7c4e9d2b10"
down_revision: Union[str, Sequence[str], None] = "0f3a7c9e2b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_requests",
        sa.Column("source_identity", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("chat_requests") as batch:
        batch.drop_column("source_identity")
