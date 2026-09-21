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
        } <= tables
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    command.upgrade(config, "head")
