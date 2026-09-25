"""Add quantity precision and generic removed lifecycle truth.

Revision ID: 6f2b1c9d4e80
Revises: a4b7c9d2e610
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6f2b1c9d4e80"
down_revision: Union[str, Sequence[str], None] = "a4b7c9d2e610"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ITEM_TRIGGER_NAMES = (
    "items_location_truth_bu",
    "items_location_truth_bi",
    "item_search_items_ad",
    "item_search_items_au",
    "item_search_items_ai",
)

_FTS_ITEM_TRIGGERS = (
    """
    CREATE TRIGGER item_search_items_ai
    AFTER INSERT ON items BEGIN
        INSERT INTO item_search_fts(rowid, name, aliases, description, tags, attributes)
        VALUES (
            new.id, new.name, '', COALESCE(new.description, ''), '',
            COALESCE(CAST(new.attributes AS TEXT), '')
        );
    END
    """,
    """
    CREATE TRIGGER item_search_items_au
    AFTER UPDATE OF name, description, attributes ON items BEGIN
        UPDATE item_search_fts
        SET name = new.name,
            description = COALESCE(new.description, ''),
            attributes = COALESCE(CAST(new.attributes AS TEXT), '')
        WHERE rowid = new.id;
    END
    """,
    """
    CREATE TRIGGER item_search_items_ad
    AFTER DELETE ON items BEGIN
        DELETE FROM item_search_fts WHERE rowid = old.id;
    END
    """,
)

_NEW_LOCATION_TRUTH = """
    (NEW.location_status = 'known' AND NEW.current_location_id IS NOT NULL
        AND NEW.state NOT IN ('removed', 'sold', 'discarded'))
    OR (
        NEW.location_status IN ('unknown', 'in_use')
        AND NEW.current_location_id IS NULL
        AND NEW.state NOT IN ('removed', 'sold', 'discarded')
    )
    OR (
        NEW.location_status = 'not_applicable'
        AND NEW.current_location_id IS NULL
        AND NEW.state = 'removed'
    )
"""

_OLD_LOCATION_TRUTH = """
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


def _drop_item_triggers() -> None:
    bind = op.get_bind()
    for name in _ITEM_TRIGGER_NAMES:
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")


def _create_item_triggers(location_truth: str) -> None:
    bind = op.get_bind()
    for operation in ("INSERT", "UPDATE OF state, current_location_id, location_status"):
        name = "items_location_truth_bi" if operation == "INSERT" else "items_location_truth_bu"
        bind.exec_driver_sql(
            f"""
            CREATE TRIGGER {name}
            BEFORE {operation} ON items
            WHEN NOT ({location_truth})
            BEGIN
                SELECT RAISE(ABORT, 'items location truth invariant violated');
            END
            """
        )
    for statement in _FTS_ITEM_TRIGGERS:
        bind.exec_driver_sql(statement)


def upgrade() -> None:
    _drop_item_triggers()
    with op.batch_alter_table("items", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "quantity_mode",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'exact'"),
            )
        )
        batch.alter_column(
            "quantity",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch.add_column(sa.Column("removal_reason", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_items_quantity_truth",
            "(quantity_mode IN ('exact', 'approximate') "
            "AND quantity IS NOT NULL AND quantity >= 1) OR "
            "(quantity_mode = 'unknown' AND quantity IS NULL)",
        )

    bind = op.get_bind()
    bind.exec_driver_sql(
        """
        UPDATE items
        SET state = 'removed',
            removal_reason = CASE state
                WHEN 'sold' THEN 'sold'
                WHEN 'discarded' THEN 'discarded'
            END,
            current_location_id = NULL,
            location_status = 'not_applicable'
        WHERE state IN ('sold', 'discarded')
        """
    )
    _create_item_triggers(_NEW_LOCATION_TRUTH)


def downgrade() -> None:
    bind = op.get_bind()
    unrepresentable = bind.exec_driver_sql(
        """
        SELECT id
        FROM items
        WHERE quantity_mode != 'exact'
           OR quantity IS NULL
           OR quantity < 1
           OR (state = 'removed' AND (
                removal_reason IS NULL OR removal_reason NOT IN ('sold', 'discarded')
           ))
           OR (state != 'removed' AND removal_reason IS NOT NULL)
        ORDER BY id
        LIMIT 1
        """
    ).first()
    if unrepresentable is not None:
        raise RuntimeError(
            "cannot downgrade quantity/removed truth: "
            f"item id={unrepresentable[0]} is not representable"
        )

    _drop_item_triggers()
    bind.exec_driver_sql(
        """
        UPDATE items
        SET state = CASE removal_reason
                WHEN 'sold' THEN 'sold'
                WHEN 'discarded' THEN 'discarded'
                ELSE state
            END
        WHERE state = 'removed'
        """
    )
    with op.batch_alter_table("items", recreate="always") as batch:
        batch.drop_constraint("ck_items_quantity_truth", type_="check")
        batch.drop_column("removal_reason")
        batch.alter_column(
            "quantity",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch.drop_column("quantity_mode")
    _create_item_triggers(_OLD_LOCATION_TRUTH)
