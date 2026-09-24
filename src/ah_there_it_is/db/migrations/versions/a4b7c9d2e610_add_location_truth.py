"""Persist authoritative item location truth.

Revision ID: a4b7c9d2e610
Revises: d24a8f1c3e90
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4b7c9d2e610"
down_revision: Union[str, Sequence[str], None] = "d24a8f1c3e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALID_TRUTH = """
    (NEW.location_status = 'known' AND NEW.current_location_id IS NOT NULL)
    OR (
        NEW.location_status IN ('unknown', 'in_use')
        AND NEW.current_location_id IS NULL
        AND NEW.state NOT IN ('discarded', 'sold')
    )
    OR (
        NEW.location_status = 'not_applicable'
        AND NEW.current_location_id IS NULL
        AND NEW.state IN ('discarded', 'sold')
    )
"""


def upgrade() -> None:
    bind = op.get_bind()
    invalid_terminal = bind.exec_driver_sql(
        """
        SELECT id
        FROM items
        WHERE state IN ('discarded', 'sold')
          AND current_location_id IS NOT NULL
        ORDER BY id
        LIMIT 1
        """
    ).first()
    if invalid_terminal is not None:
        raise RuntimeError(
            "cannot enforce location truth: legacy terminal item "
            f"id={invalid_terminal[0]} has a current location"
        )
    op.add_column(
        "items",
        sa.Column(
            "location_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unknown'"),
        ),
    )
    bind.exec_driver_sql(
        """
        UPDATE items
        SET location_status = CASE
            WHEN current_location_id IS NOT NULL THEN 'known'
            WHEN state = 'discarded' THEN 'not_applicable'
            ELSE 'unknown'
        END
        """
    )
    for operation in ("INSERT", "UPDATE OF state, current_location_id, location_status"):
        trigger = (
            "items_location_truth_bi"
            if operation == "INSERT"
            else "items_location_truth_bu"
        )
        bind.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger}
            BEFORE {operation} ON items
            WHEN NOT ({_VALID_TRUTH})
            BEGIN
                SELECT RAISE(ABORT, 'items location truth invariant violated');
            END
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    sold_count = bind.exec_driver_sql(
        "SELECT count(*) FROM items WHERE state = 'sold'"
    ).scalar_one()
    if sold_count:
        raise RuntimeError("cannot downgrade location truth while sold items exist")
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS items_location_truth_bu")
    bind.exec_driver_sql("DROP TRIGGER IF EXISTS items_location_truth_bi")
    op.drop_column("items", "location_status")
