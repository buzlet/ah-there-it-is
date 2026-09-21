from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from ah_there_it_is.db.session import create_db_engine


def test_initial_migration_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    url = f"sqlite:///{database}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "head")

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
        } <= tables
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

    command.downgrade(config, "base")

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

    command.upgrade(config, "head")


def test_search_migration_backfills_existing_stage1_items(tmp_path: Path) -> None:
    from sqlalchemy.orm import Session

    from ah_there_it_is.services import InventoryService, SearchService

    database = tmp_path / "stage1_upgrade.db"
    url = f"sqlite:///{database}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "ae83dd1ff537")

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

    command.upgrade(config, "head")

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            assert search.search_items("SPI flash")[0].id == item_id
            assert search.search_items("чёрный программатор")[0].id == item_id
            assert search.search_items("BIOS")[0].id == item_id
    finally:
        engine.dispose()
