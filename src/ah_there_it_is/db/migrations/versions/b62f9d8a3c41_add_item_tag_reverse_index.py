"""add item tag reverse lookup index

Revision ID: b62f9d8a3c41
Revises: a31d7f4e9c20
Create Date: 2026-09-23 17:55:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b62f9d8a3c41"
down_revision: Union[str, Sequence[str], None] = "a31d7f4e9c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_item_tags_tag_id", "item_tags", ["tag_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_item_tags_tag_id", table_name="item_tags")
