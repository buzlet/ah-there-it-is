"""Add external photo references associated with Items."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0f3a7c9e2b11"
down_revision: Union[str, Sequence[str], None] = "6f2b1c9d4e80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "item_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("media_reference", sa.String(length=1000), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_item_media_provider_nonblank",
        ),
        sa.CheckConstraint(
            "length(trim(media_reference)) > 0",
            name="ck_item_media_reference_nonblank",
        ),
        sa.CheckConstraint(
            "position >= 0",
            name="ck_item_media_position_nonnegative",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "item_id",
            "provider",
            "media_reference",
            name="uq_item_media_item_provider_reference",
        ),
    )
    op.create_index("ix_item_media_item_id", "item_media", ["item_id"], unique=False)
    op.create_index(
        "ix_item_media_item_position",
        "item_media",
        ["item_id", "position", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_item_media_item_position", table_name="item_media")
    op.drop_index("ix_item_media_item_id", table_name="item_media")
    op.drop_table("item_media")
