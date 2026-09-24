from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from ah_there_it_is.db.migrations import (
    check_database_schema,
    downgrade_database,
    upgrade_database,
)
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.storage import CURRENT_SCHEMA_REVISION, validate_database


def test_initial_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database}"
    upgrade_database(url)

    engine = create_db_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert {
            "alembic_version",
            "aliases",
            "categories",
            "events",
            "item_tags",
            "items",
            "locations",
            "tags",
            "conversations",
            "messages",
            "agent_run_logs",
            "agent_feedback",
            "experiment_runs",
            "experiment_reviews",
            "chat_requests",
        } <= tables
        inspector = inspect(engine)
        chat_columns = {column["name"] for column in inspector.get_columns("chat_requests")}
        assert {"recovered_from_id", "recovery_note"} <= chat_columns
        chat_indexes = {index["name"] for index in inspector.get_indexes("chat_requests")}
        assert "ix_chat_requests_recovered_from_id" in chat_indexes
        chat_foreign_keys = inspector.get_foreign_keys("chat_requests")
        assert any(
            foreign_key["referred_table"] == "chat_requests"
            and foreign_key["constrained_columns"] == ["recovered_from_id"]
            for foreign_key in chat_foreign_keys
        )
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type='table' AND name='item_search_fts'"
                )
            ) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type='trigger' AND name='item_search_items_ai'"
                )
            ) == 1
    finally:
        engine.dispose()

    downgrade_database(url)

    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE name LIKE 'item_search_fts%' OR name LIKE 'item_search_%'"
                )
            ) == 0
    finally:
        engine.dispose()

    upgrade_database(url)


def test_search_migration_backfills_existing_stage1_items(tmp_path: Path) -> None:
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from ah_there_it_is.services import SearchService

    database = tmp_path / "stage1_upgrade.db"
    url = f"sqlite:///{database}"
    upgrade_database(url, "ae83dd1ff537")

    engine = create_db_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO items (
                    id, name, normalized_name, description, state, category_id,
                    current_location_id, quantity, attributes, created_at, updated_at
                ) VALUES (
                    1, 'CH341A programmer', 'ch341a programmer',
                    'USB программатор для SPI flash и BIOS', 'unknown', NULL,
                    NULL, 1, '{}', '2026-09-24', '2026-09-24'
                )
            """))
            connection.execute(text("""
                INSERT INTO aliases (item_id, name, normalized_name)
                VALUES (1, 'чёрный программатор', 'чёрный программатор')
            """))
            connection.execute(text("""
                INSERT INTO events (
                    event_type, item_id, from_location_id, to_location_id,
                    payload, original_text, created_at
                ) VALUES (
                    'item_taken', 1, NULL, NULL, '{}', NULL, '2026-09-24'
                )
            """))
    finally:
        engine.dispose()

    upgrade_database(url)

    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT location_status FROM items WHERE id = 1"
            )) == "unknown"
        with Session(engine) as session:
            search = SearchService(session)
            assert search.search_items("SPI flash")[0].id == 1
            assert search.search_items("чёрный программатор")[0].id == 1
            assert search.search_items("BIOS")[0].id == 1
    finally:
        engine.dispose()



def test_location_truth_migration_backfill_and_database_invariants(
    tmp_path: Path,
) -> None:
    import sqlite3

    import pytest

    database = tmp_path / "location-truth.db"
    url = f"sqlite:///{database}"
    upgrade_database(url, "d24a8f1c3e90")

    with sqlite3.connect(database) as connection:
        connection.execute("""
            INSERT INTO locations (
                id, parent_id, name, normalized_name, description, created_at, updated_at
            ) VALUES (1, NULL, 'Shelf', 'shelf', NULL, '2026-09-24', '2026-09-24')
        """)
        base = """
            INSERT INTO items (
                id, name, normalized_name, description, state, category_id,
                current_location_id, quantity, attributes, created_at, updated_at
            ) VALUES (?, ?, ?, NULL, ?, NULL, ?, 1, '{}', '2026-09-24', '2026-09-24')
        """
        connection.execute(base, (1, "Located", "located", "used", 1))
        connection.execute(base, (2, "Discarded", "discarded", "discarded", None))
        connection.execute(base, (3, "Taken", "taken", "for_sale", None))
        connection.execute("""
            INSERT INTO events (
                event_type, item_id, from_location_id, to_location_id,
                payload, original_text, created_at
            ) VALUES ('item_taken', 3, NULL, NULL, '{}', NULL, '2026-09-24')
        """)

    upgrade_database(url)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT id, location_status FROM items ORDER BY id"
        ).fetchall() == [
            (1, "known"),
            (2, "not_applicable"),
            (3, "unknown"),
        ]

        invalid_rows = [
            (10, "known-null", "known-null", "used", None, "known"),
            (11, "unknown-located", "unknown-located", "used", 1, "unknown"),
            (12, "terminal-unknown", "terminal-unknown", "sold", None, "unknown"),
            (13, "active-not-applicable", "active-not-applicable", "used", None, "not_applicable"),
        ]
        statement = """
            INSERT INTO items (
                id, name, normalized_name, description, state, category_id,
                current_location_id, location_status, quantity, attributes,
                created_at, updated_at
            ) VALUES (?, ?, ?, NULL, ?, NULL, ?, ?, 1, '{}', '2026-09-24', '2026-09-24')
        """
        for row in invalid_rows:
            with pytest.raises(sqlite3.IntegrityError, match="location truth invariant"):
                connection.execute(statement, row)
            connection.rollback()

        connection.execute(statement, (14, "In use", "in use", "used", None, "in_use"))
        connection.commit()
        assert connection.execute(
            "SELECT location_status FROM items WHERE id = 14"
        ).fetchone() == ("in_use",)



def test_location_truth_migration_stops_on_terminal_item_with_location(
    tmp_path: Path,
) -> None:
    import sqlite3

    import pytest

    database = tmp_path / "location-truth-conflict.db"
    url = f"sqlite:///{database}"
    upgrade_database(url, "d24a8f1c3e90")
    with sqlite3.connect(database) as connection:
        connection.execute("""
            INSERT INTO locations (
                id, parent_id, name, normalized_name, description, created_at, updated_at
            ) VALUES (1, NULL, 'Shelf', 'shelf', NULL, '2026-09-24', '2026-09-24')
        """)
        connection.execute("""
            INSERT INTO items (
                id, name, normalized_name, description, state, category_id,
                current_location_id, quantity, attributes, created_at, updated_at
            ) VALUES (
                1, 'Discarded', 'discarded', NULL, 'discarded', NULL,
                1, 1, '{}', '2026-09-24', '2026-09-24'
            )
        """)

    with pytest.raises(RuntimeError, match="legacy terminal item id=1"):
        upgrade_database(url)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("d24a8f1c3e90",)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(items)")
        }
        assert "location_status" not in columns


def test_packaged_upgrade_is_cwd_independent_and_ignores_ambient_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "fresh.db"
    ambient = tmp_path / "ambient.db"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", f"sqlite:///{ambient}")
    monkeypatch.chdir(unrelated)

    upgrade_database(f"sqlite:///{database}")

    assert validate_database(database).alembic_revision == CURRENT_SCHEMA_REVISION
    assert not ambient.exists()


def test_item_tag_reverse_index_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "tag-index.db"
    url = f"sqlite:///{database}"
    upgrade_database(url)

    engine = create_db_engine(url)
    try:
        indexes = {index["name"] for index in inspect(engine).get_indexes("item_tags")}
        assert "ix_item_tags_tag_id" in indexes
    finally:
        engine.dispose()

    downgrade_database(url, "a31d7f4e9c20")
    engine = create_db_engine(url)
    try:
        indexes = {index["name"] for index in inspect(engine).get_indexes("item_tags")}
        assert "ix_item_tags_tag_id" not in indexes
    finally:
        engine.dispose()

    upgrade_database(url)
    check_database_schema(url)
    assert validate_database(database).alembic_revision == CURRENT_SCHEMA_REVISION


def test_receipt_migration_defaults_existing_runs_to_empty(tmp_path: Path) -> None:
    database = tmp_path / "receipts.db"
    url = f"sqlite:///{database}"
    upgrade_database(url, "b62f9d8a3c41")
    engine = create_db_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO conversations (id, created_at, updated_at)
                VALUES (1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """))
            connection.execute(text("""
                INSERT INTO agent_run_logs (
                    conversation_id, prompt_version, prompt_hash, system_prompt,
                    llm_provider, llm_model, llm_config, input_messages,
                    tool_trace, rounds, status, created_at
                ) VALUES (
                    1, 'v1', 'hash', 'prompt', 'test', 'model', '{}', '[]',
                    '[]', 1, 'completed', CURRENT_TIMESTAMP
                )
            """))
    finally:
        engine.dispose()

    upgrade_database(url)
    engine = create_db_engine(url)
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("agent_run_logs")}
        assert "mutation_receipts" in columns
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT mutation_receipts FROM agent_run_logs")) == "[]"
    finally:
        engine.dispose()
    check_database_schema(url)
