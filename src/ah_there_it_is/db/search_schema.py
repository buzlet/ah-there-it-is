"""SQLite FTS5 schema used for deterministic item candidate retrieval."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Connection

FTS_TABLE = "item_search_fts"

# A standalone FTS table keeps Stage 2 simple and allows trigger-maintained aggregate
# text from aliases/tags without adding denormalized columns to the domain tables.
FTS_SCHEMA_SQL: tuple[str, ...] = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS item_search_fts USING fts5(
        name,
        aliases,
        description,
        tags,
        attributes,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_items_ai
    AFTER INSERT ON items BEGIN
        INSERT INTO item_search_fts(rowid, name, aliases, description, tags, attributes)
        VALUES (
            new.id,
            new.name,
            '',
            COALESCE(new.description, ''),
            '',
            COALESCE(CAST(new.attributes AS TEXT), '')
        );
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_items_au
    AFTER UPDATE OF name, description, attributes ON items BEGIN
        UPDATE item_search_fts
        SET name = new.name,
            description = COALESCE(new.description, ''),
            attributes = COALESCE(CAST(new.attributes AS TEXT), '')
        WHERE rowid = new.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_items_ad
    AFTER DELETE ON items BEGIN
        DELETE FROM item_search_fts WHERE rowid = old.id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_aliases_ai
    AFTER INSERT ON aliases BEGIN
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ')
            FROM aliases
            WHERE item_id = new.item_id
        ), '')
        WHERE rowid = new.item_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_aliases_au
    AFTER UPDATE OF name, item_id ON aliases BEGIN
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ')
            FROM aliases
            WHERE item_id = old.item_id
        ), '')
        WHERE rowid = old.item_id;
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ')
            FROM aliases
            WHERE item_id = new.item_id
        ), '')
        WHERE rowid = new.item_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_aliases_ad
    AFTER DELETE ON aliases BEGIN
        UPDATE item_search_fts
        SET aliases = COALESCE((
            SELECT group_concat(name, ' ')
            FROM aliases
            WHERE item_id = old.item_id
        ), '')
        WHERE rowid = old.item_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_item_tags_ai
    AFTER INSERT ON item_tags BEGIN
        UPDATE item_search_fts
        SET tags = COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags
            JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = new.item_id
        ), '')
        WHERE rowid = new.item_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_item_tags_ad
    AFTER DELETE ON item_tags BEGIN
        UPDATE item_search_fts
        SET tags = COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags
            JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = old.item_id
        ), '')
        WHERE rowid = old.item_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS item_search_tags_au
    AFTER UPDATE OF name ON tags BEGIN
        UPDATE item_search_fts
        SET tags = COALESCE((
            SELECT group_concat(tags.name, ' ')
            FROM item_tags
            JOIN tags ON tags.id = item_tags.tag_id
            WHERE item_tags.item_id = item_search_fts.rowid
        ), '')
        WHERE rowid IN (
            SELECT item_id FROM item_tags WHERE tag_id = new.id
        );
    END
    """,
)

FTS_DROP_SQL: tuple[str, ...] = (
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


def install_fts_schema(connection: Connection) -> None:
    _execute_all(connection, FTS_SCHEMA_SQL)


def drop_fts_schema(connection: Connection) -> None:
    _execute_all(connection, FTS_DROP_SQL)


def rebuild_fts_index(connection: Connection) -> None:
    """Rebuild all indexed item text, useful after importing pre-existing rows."""
    connection.exec_driver_sql("DELETE FROM item_search_fts")
    connection.exec_driver_sql(
        """
        INSERT INTO item_search_fts(rowid, name, aliases, description, tags, attributes)
        SELECT
            items.id,
            items.name,
            COALESCE((
                SELECT group_concat(aliases.name, ' ')
                FROM aliases
                WHERE aliases.item_id = items.id
            ), ''),
            COALESCE(items.description, ''),
            COALESCE((
                SELECT group_concat(tags.name, ' ')
                FROM item_tags
                JOIN tags ON tags.id = item_tags.tag_id
                WHERE item_tags.item_id = items.id
            ), ''),
            COALESCE(CAST(items.attributes AS TEXT), '')
        FROM items
        """
    )


def _execute_all(connection: Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        connection.exec_driver_sql(statement)
