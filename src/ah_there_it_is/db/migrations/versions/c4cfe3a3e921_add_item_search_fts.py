"""add item search fts

Revision ID: c4cfe3a3e921
Revises: ae83dd1ff537
Create Date: 2026-09-21 19:20:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c4cfe3a3e921"
down_revision: Union[str, Sequence[str], None] = "ae83dd1ff537"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATE_SQL = (
    """
    CREATE VIRTUAL TABLE item_search_fts USING fts5(
        name,
        aliases,
        description,
        tags,
        attributes,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """,
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
    """
    CREATE TRIGGER item_search_aliases_ai
    AFTER INSERT ON aliases BEGIN
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ') FROM aliases WHERE item_id = new.item_id
        ), '')
        WHERE rowid = new.item_id;
    END
    """,
    """
    CREATE TRIGGER item_search_aliases_au
    AFTER UPDATE OF name, item_id ON aliases BEGIN
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ') FROM aliases WHERE item_id = old.item_id
        ), '')
        WHERE rowid = old.item_id;
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ') FROM aliases WHERE item_id = new.item_id
        ), '')
        WHERE rowid = new.item_id;
    END
    """,
    """
    CREATE TRIGGER item_search_aliases_ad
    AFTER DELETE ON aliases BEGIN
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ') FROM aliases WHERE item_id = old.item_id
        ), '')
        WHERE rowid = old.item_id;
    END
    """,
    """
    CREATE TRIGGER item_search_item_tags_ai
    AFTER INSERT ON item_tags BEGIN
        UPDATE item_search_fts
        SET tags = COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = new.item_id
        ), '')
        WHERE rowid = new.item_id;
    END
    """,
    """
    CREATE TRIGGER item_search_item_tags_ad
    AFTER DELETE ON item_tags BEGIN
        UPDATE item_search_fts
        SET tags = COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = old.item_id
        ), '')
        WHERE rowid = old.item_id;
    END
    """,
    """
    CREATE TRIGGER item_search_tags_au
    AFTER UPDATE OF name ON tags BEGIN
        UPDATE item_search_fts
        SET tags = COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = item_search_fts.rowid
        ), '')
        WHERE rowid IN (SELECT item_id FROM item_tags WHERE tag_id = new.id);
    END
    """,
    """
    INSERT INTO item_search_fts(rowid, name, aliases, description, tags, attributes)
    SELECT
        items.id,
        items.name,
        COALESCE((SELECT group_concat(aliases.name, ' ') FROM aliases WHERE aliases.item_id = items.id), ''),
        COALESCE(items.description, ''),
        COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = items.id
        ), ''),
        COALESCE(CAST(items.attributes AS TEXT), '')
    FROM items
    """,
)

_DROP_SQL = (
    "DROP TRIGGER IF EXISTS item_search_tags_au",
    "DROP TRIGGER IF EXISTS item_search_item_tags_ad",
    "DROP TRIGGER IF EXISTS item_search_item_tags_ai",
    "DROP TRIGGER IF EXISTS item_search_aliases_ad",
    "DROP TRIGGER IF EXISTS item_search_aliases_au",
    "DROP TRIGGER IF EXISTS item_search_aliases_ai",
    "DROP TRIGGER IF EXISTS item_search_items_ad",
    "DROP TRIGGER IF EXISTS item_search_items_au",
    "DROP TRIGGER IF EXISTS item_search_items_ai",
    "DROP TABLE IF EXISTS item_search_fts",
)


def upgrade() -> None:
    bind = op.get_bind()
    for statement in _CREATE_SQL:
        bind.exec_driver_sql(statement)


def downgrade() -> None:
    bind = op.get_bind()
    for statement in _DROP_SQL:
        bind.exec_driver_sql(statement)
