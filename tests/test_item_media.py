from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import Base, Event, Item, ItemMedia
from ah_there_it_is.domain.exceptions import DuplicateEntityError
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


def test_item_photo_service_orders_updates_and_records_history(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Camera body")

    first = inventory.attach_item_photo(
        item.id, " telegram ", " file-front ", caption="front", position=2
    )
    second = inventory.attach_item_photo(
        item.id, "telegram", "file-back", caption="back", position=1
    )
    assert [photo.id for photo in inventory.list_item_photos(item.id)] == [
        second.id,
        first.id,
    ]
    with pytest.raises(DuplicateEntityError):
        inventory.attach_item_photo(item.id, "telegram", "file-front")

    updated = inventory.update_item_photo(first.id, caption=None, position=0)
    assert updated.id == first.id
    assert updated.caption is None
    assert updated.position == 0
    assert [photo.id for photo in inventory.list_item_photos(item.id)] == [
        first.id,
        second.id,
    ]

    detached = inventory.detach_item_photo(second.id)
    assert detached.id == second.id
    assert [photo.id for photo in inventory.list_item_photos(item.id)] == [first.id]
    history = inventory.get_item_history(item.id)
    photo_events = [event for event in history if event.event_type.startswith("item_photo_")]
    assert [event.event_type for event in photo_events] == [
        "item_photo_attached",
        "item_photo_attached",
        "item_photo_updated",
        "item_photo_detached",
    ]
    assert photo_events[2].payload["before"]["media_id"] == first.id
    assert photo_events[2].payload["after"]["caption"] is None
    assert photo_events[3].payload["before"]["media_id"] == second.id
    assert all("bytes" not in str(event.payload).lower() for event in photo_events)


def test_item_photo_service_retains_media_across_remove_restore(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Retained camera")
    media = inventory.attach_item_photo(item.id, "local", "opaque-1")

    inventory.remove_item(item.id, reason="broken", reason_source="explicit")
    assert [photo.id for photo in inventory.list_item_photos(item.id)] == [media.id]
    inventory.restore_item(item.id, state="unknown", location_id=None)
    assert [photo.id for photo in inventory.list_item_photos(item.id)] == [media.id]


def test_item_photo_service_split_keeps_source_media_and_not_child_media(
    session: Session,
) -> None:
    inventory = InventoryService(session)
    shelf = inventory.create_location("Shelf")
    bin_ = inventory.create_location("Bin")
    source = inventory.create_item("Bolts", location_id=shelf.id, quantity=10)
    first = inventory.attach_item_photo(source.id, "local", "bolts-front")
    second = inventory.attach_item_photo(source.id, "local", "bolts-back")

    child = inventory.move_item(
        source.id,
        bin_.id,
        portion={"mode": "exact", "value": 3},
    )

    assert [photo.id for photo in inventory.list_item_photos(source.id)] == [
        first.id,
        second.id,
    ]
    assert inventory.list_item_photos(child.id) == []


def test_item_photo_agent_attach_and_immediate_undo(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Agent camera")
    attach_run = AgentRunner(
        session,
        ScriptedLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            id="1",
                            name="search_items",
                            arguments={"query": "Agent camera"},
                        ),
                    )
                ),
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            id="2",
                            name="attach_item_photo",
                            arguments={
                                "item_id": item.id,
                                "provider": "telegram",
                                "media_reference": "file-agent-1",
                            },
                        ),
                    )
                ),
                LLMResponse(content="Attached."),
            ]
        ),
    ).run("Attach the supplied photo reference")
    assert attach_run.receipts[0].operation == "attach_item_photo"
    assert attach_run.receipts[0].entity_type == "media"
    assert [photo.media_reference for photo in inventory.list_item_photos(item.id)] == [
        "file-agent-1"
    ]

    AgentRunner(
        session,
        ScriptedLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(id="u", name="undo_last_action", arguments={}),
                    )
                ),
                LLMResponse(content="Undone."),
            ]
        ),
    ).run("Undo that", conversation_id=attach_run.conversation_id)
    assert inventory.list_item_photos(item.id) == []
