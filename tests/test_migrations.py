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
    from sqlalchemy.orm import Session

    from ah_there_it_is.services import InventoryService, SearchService

    database = tmp_path / "stage1_upgrade.db"
    url = f"sqlite:///{database}"
    upgrade_database(url, "ae83dd1ff537")

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            inventory = InventoryService(session)
            item = inventory.create_item(
                "CH341A programmer",
                description="USB программатор для SPI flash и BIOS",
                aliases=["чёрный программатор"],
                tags=["BIOS"],
                attributes={"interface": "USB"},
            )
            item_id = item.id
    finally:
        engine.dispose()

    upgrade_database(url)

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            assert search.search_items("SPI flash")[0].id == item_id
            assert search.search_items("чёрный программатор")[0].id == item_id
            assert search.search_items("BIOS")[0].id == item_id
    finally:
        engine.dispose()


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
