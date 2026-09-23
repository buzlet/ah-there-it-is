# search_consistency.py
"""Read-only consistency checks for the derived item search index."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import sqlite3
from typing import Any

from ah_there_it_is.db.search_schema import FTS_SCHEMA_SQL, FTS_TABLE

_SAMPLE_LIMIT = 20


@dataclass(frozen=True)
class SearchConsistency:
    missing_count: int
    mismatched_count: int
    extra_count: int
    missing_ids: tuple[int, ...]
    mismatched_ids: tuple[int, ...]
    extra_ids: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return not (self.missing_count or self.mismatched_count or self.extra_count)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _execute(connection: Any, sql: str):
    if hasattr(connection, 'exec_driver_sql'):
        return connection.exec_driver_sql(sql)
    return connection.execute(sql)


def expected_fts_objects(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return absent or non-FTS objects from the current installed schema."""
    expected = [(FTS_TABLE, 'table', FTS_SCHEMA_SQL[0])]
    expected.extend(
        (re.search(r'CREATE TRIGGER IF NOT EXISTS (\w+)', sql).group(1), 'trigger', sql)
        for sql in FTS_SCHEMA_SQL[1:]
    )
    actual = {
        row[0]: (row[1], row[2])
        for row in connection.execute(
            "SELECT name, type, sql FROM sqlite_master WHERE name = 'item_search_fts' OR name LIKE 'item_search_%'"
        )
    }

    def canonical(sql: str) -> str:
        return re.sub(r'\s+', '', re.sub(r'\bIF NOT EXISTS\b', '', sql, flags=re.I)).casefold()

    missing = []
    for name, kind, ddl in expected:
        found = actual.get(name)
        if found is None or found[0] != kind or canonical(found[1] or '') != canonical(ddl):
            missing.append(name)
    return tuple(missing)


def search_consistency(connection: Any) -> SearchConsistency:
    """Compare authoritative item text with FTS rows without loading all IDs."""
    missing_sql = """
        SELECT items.id FROM items
        LEFT JOIN item_search_fts ON item_search_fts.rowid = items.id
        WHERE item_search_fts.rowid IS NULL
    """
    mismatched_sql = """
        SELECT items.id FROM items
        JOIN item_search_fts ON item_search_fts.rowid = items.id
        WHERE item_search_fts.name IS NOT items.name
           OR item_search_fts.description IS NOT COALESCE(items.description, '')
           OR item_search_fts.aliases IS NOT COALESCE((
                SELECT group_concat(aliases.name, ' ') FROM aliases
                WHERE aliases.item_id = items.id
           ), '')
           OR item_search_fts.tags IS NOT COALESCE((
                SELECT group_concat(tags.name, ' ') FROM item_tags
                JOIN tags ON tags.id = item_tags.tag_id
                WHERE item_tags.item_id = items.id
           ), '')
           OR item_search_fts.attributes IS NOT COALESCE(CAST(items.attributes AS TEXT), '')
    """
    extra_sql = """
        SELECT rowid FROM item_search_fts
        WHERE rowid NOT IN (SELECT id FROM items)
    """

    def summary(query: str) -> tuple[int, tuple[int, ...]]:
        row = _execute(connection, f'SELECT count(*) FROM ({query})').fetchone()
        count = int(row[0])
        ids = tuple(int(row[0]) for row in _execute(connection, f'{query} ORDER BY 1 LIMIT {_SAMPLE_LIMIT}'))
        return count, ids

    missing_count, missing_ids = summary(missing_sql)
    mismatched_count, mismatched_ids = summary(mismatched_sql)
    extra_count, extra_ids = summary(extra_sql)
    return SearchConsistency(missing_count, mismatched_count, extra_count, missing_ids, mismatched_ids, extra_ids)
