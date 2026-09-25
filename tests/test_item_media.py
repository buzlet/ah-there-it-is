from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import Base, Event, Item, ItemMedia
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService


def test_fresh_metadata_has_item_media_constraints() -> None:
    engine = create_db_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        columns = {column["name"] for column in inspect(engine).get_columns("item_media")}
        assert columns == {
            "id", "item_id", "provider", "media_reference", "caption", "position",
            "created_at", "updated_at",
        }
        assert not any("bytes" in column.lower() or "blob" in column.lower() for column in columns)
    finally:
        engine.dispose()


def test_upgrade_fresh_and_populated_database_creates_item_media(tmp_path) -> None:
    database = tmp_path / "media.db"
    url = f"sqlite:///{database}"
    upgrade_database(url)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            item = InventoryService(session).create_item("Camera body")
            session.add(
                ItemMedia(
                    item_id=item.id,
                    provider="local-test",
                    media_reference="ref-1",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
    finally:
        engine.dispose()

    upgraded = tmp_path / "upgrade.db"
    upgrade_database(f"sqlite:///{upgraded}", "6f2b1c9d4e80")
    engine = create_db_engine(f"sqlite:///{upgraded}")
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO items (name, normalized_name, state, location_status, quantity_mode, quantity, attributes, created_at, updated_at) VALUES ('Existing', 'existing', 'unknown', 'unknown', 'exact', 1, '{}', '2026', '2026')"))
        upgrade_database(f"sqlite:///{upgraded}")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM item_media")) == 0
    finally:
        engine.dispose()


def test_item_media_database_constraints_and_removed_retention(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Tagged item")
    media = ItemMedia(
        item_id=item.id,
        provider="telegram",
        media_reference="file-123",
        caption="front",
        position=2,
    )
    session.add(media)
    session.commit()

    with pytest.raises(IntegrityError):
        session.add(ItemMedia(item_id=item.id, provider="telegram", media_reference="file-123"))
        session.commit()
    session.rollback()

    with pytest.raises(IntegrityError):
        session.add(ItemMedia(item_id=item.id, provider=" ", media_reference="other"))
        session.commit()
    session.rollback()

    inventory.remove_item(item.id, reason="damaged", reason_source="explicit")
    assert session.scalar(select(ItemMedia.id).where(ItemMedia.item_id == item.id)) == media.id
    assert session.scalar(select(Item.state).where(Item.id == item.id)) == "removed"
