# d24a8f1c3e90_add_agent_mutation_receipts.py
"""Persist committed agent mutation receipts.

Revision ID: d24a8f1c3e90
Revises: b62f9d8a3c41
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d24a8f1c3e90"
down_revision: Union[str, Sequence[str], None] = "b62f9d8a3c41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_run_logs",
        sa.Column(
            "mutation_receipts", sa.JSON(), nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_run_logs", "mutation_receipts")
