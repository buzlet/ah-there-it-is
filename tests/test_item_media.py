from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import Base, Event, Item, ItemMedia
from ah_there_it_is.domain.exceptions import DuplicateEntityError
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.catalog import CatalogService
from ah_there_it_is.services.undo import UndoService, UndoUnavailableError


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


def test_media_caption_validation_is_shared_at_service_boundary(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Caption target")

    with pytest.raises(ValueError, match="caption"):
        inventory.attach_item_photo(item.id, "local", "bad-type", caption=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="caption"):
        inventory.attach_item_photo(item.id, "local", "too-long", caption="x" * 20_001)
    assert inventory.list_item_photos(item.id) == []

    media = inventory.attach_item_photo(item.id, "local", "valid", caption="front")
    with pytest.raises(ValueError, match="caption"):
        inventory.update_item_photo(media.id, caption={"malformed": True})  # type: ignore[arg-type]
    assert inventory.list_item_photos(item.id)[0].caption == "front"


def test_media_list_projection_batches_association_reads(session: Session) -> None:
    inventory = InventoryService(session)
    for index in range(20):
        item = inventory.create_item(f"Media item {index}")
        inventory.attach_item_photo(item.id, "local", f"photo-{index}")

    statements: list[str] = []
    def count_media_reads(_conn, _cursor, statement, _params, _context, _many):
        if "FROM item_media" in statement:
            statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", count_media_reads)
    try:
        session.expire_all()
        page = CatalogService(session).item_page(page_size=20)
        assert len(page.items) == 20
        assert all(len(item["media"]) == 1 for item in page.items)
        assert len(statements) <= 2

        statements.clear()
        session.expire_all()
        rows = CatalogService(session).list_items()
        assert len(rows) == 20
        assert all(len(item["media"]) == 1 for item in rows)
        assert len(statements) <= 2
    finally:
        event.remove(engine, "before_cursor_execute", count_media_reads)


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


@pytest.mark.parametrize(
    ("source_mode", "source_quantity", "portion", "action"),
    [
        ("approximate", 20, {"mode": "exact", "value": 3}, "move"),
        ("unknown", None, {"mode": "exact", "value": 3}, "take"),
        ("exact", 10, {"mode": "exact", "value": 3}, "remove"),
    ],
)
def test_other_partial_lifecycle_splits_leave_media_on_source_only(
    session: Session, source_mode, source_quantity, portion, action
) -> None:
    inventory = InventoryService(session)
    shelf = inventory.create_location("Photo shelf")
    destination = inventory.create_location("Photo destination")
    source = inventory.create_item(
        "Photo lot", location_id=shelf.id,
        quantity_mode=source_mode, quantity=source_quantity,
    )
    media = inventory.attach_item_photo(source.id, "local", "source-photo")
    if action == "move":
        child = inventory.move_item(source.id, destination.id, portion=portion)
    elif action == "take":
        child = inventory.take_item(source.id, portion=portion)
    else:
        child = inventory.remove_item(
            source.id, reason="partial removal", reason_source="explicit", portion=portion
        )

    assert child.id != source.id
    assert [photo.id for photo in inventory.list_item_photos(source.id)] == [media.id]
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


def test_undo_compensates_two_photo_attaches_in_one_turn(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Two photo camera")
    run = AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="search", name="search_items", arguments={"query": "Two photo camera"}
            ),)),
            LLMResponse(tool_calls=(
                ToolCall(id="front", name="attach_item_photo", arguments={
                    "item_id": item.id, "provider": "local", "media_reference": "front"
                }),
                ToolCall(id="back", name="attach_item_photo", arguments={
                    "item_id": item.id, "provider": "local", "media_reference": "back"
                }),
            )),
            LLMResponse(content="Attached both."),
        ]),
    ).run("Attach both supplied references")
    assert [receipt.operation for receipt in run.receipts] == [
        "attach_item_photo", "attach_item_photo"
    ]
    assert len(inventory.list_item_photos(item.id)) == 2

    AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="undo", name="undo_last_action", arguments={}
            ),)),
            LLMResponse(content="Undone."),
        ]),
    ).run("Undo", conversation_id=run.conversation_id)
    assert inventory.list_item_photos(item.id) == []
    assert len([event for event in inventory.get_item_history(item.id)
                if event.event_type == "item_undo_compensated"]) == 2


def test_media_undo_stale_post_state_rolls_back_all_compensation(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Stale photo camera")
    run = AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="search", name="search_items", arguments={"query": "Stale photo camera"}
            ),)),
            LLMResponse(tool_calls=(
                ToolCall(id="first", name="attach_item_photo", arguments={
                    "item_id": item.id, "provider": "local", "media_reference": "first"
                }),
                ToolCall(id="second", name="attach_item_photo", arguments={
                    "item_id": item.id, "provider": "local", "media_reference": "second"
                }),
            )),
            LLMResponse(content="Attached."),
        ]),
    ).run("Attach both references")
    photos = inventory.list_item_photos(item.id)
    inventory.update_item_photo(photos[0].id, caption="changed after turn")
    before_event_ids = [event.id for event in inventory.get_item_history(item.id)]

    with pytest.raises(UndoUnavailableError, match="post-state"):
        UndoService(session, autocommit=True).undo(run.conversation_id)

    assert [photo.id for photo in inventory.list_item_photos(item.id)] == [
        photo.id for photo in photos
    ]
    assert [event.id for event in inventory.get_item_history(item.id)] == before_event_ids


def test_media_attach_and_remove_same_turn_undo_is_atomic(session: Session) -> None:
    inventory = InventoryService(session)
    shelf = inventory.create_location("Combined shelf")
    item = inventory.create_item("Combined camera", location_id=shelf.id, quantity=2)
    run = AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="search", name="search_items", arguments={"query": "Combined camera"}
            ),)),
            LLMResponse(tool_calls=(
                ToolCall(id="photo", name="attach_item_photo", arguments={
                    "item_id": item.id,
                    "provider": "local",
                    "media_reference": "combined-photo",
                    "caption": "front",
                }),
                ToolCall(id="remove", name="remove_item", arguments={
                    "item_id": item.id,
                    "reason": "temporary removal",
                    "reason_source": "explicit",
                }),
            )),
            LLMResponse(content="Done."),
        ]),
    ).run("Attach this reference and remove the camera")

    assert [receipt.operation for receipt in run.receipts] == [
        "attach_item_photo", "remove_item"
    ]
    assert inventory.get_item(item.id).state == "removed"
    attached = inventory.list_item_photos(item.id)
    assert [photo.media_reference for photo in attached] == ["combined-photo"]

    AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="undo", name="undo_last_action", arguments={}
            ),)),
            LLMResponse(content="Undone."),
        ]),
    ).run("Undo", conversation_id=run.conversation_id)

    restored = inventory.get_item(item.id)
    assert restored.state == "unknown"
    assert restored.current_location_id == shelf.id
    assert (restored.quantity_mode, restored.quantity) == ("exact", 2)
    assert inventory.list_item_photos(item.id) == []


def test_media_update_detach_and_quantity_same_turn_undo_restores_all(
    session: Session,
) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Receipt camera", quantity=5)
    media = inventory.attach_item_photo(
        item.id, "local", "receipt-photo", caption="before", position=3
    )
    run = AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="search", name="search_items", arguments={"query": "Receipt camera"}
            ),)),
            LLMResponse(tool_calls=(ToolCall(
                id="photos", name="list_item_photos", arguments={"item_id": item.id}
            ),)),
            LLMResponse(tool_calls=(
                ToolCall(id="quantity", name="change_item_quantity", arguments={
                    "item_id": item.id,
                    "quantity_mode": "approximate",
                    "quantity": 4,
                    "reason": "recounted",
                    "reason_source": "explicit",
                }),
                ToolCall(id="update", name="update_item_photo", arguments={
                    "media_id": media.id,
                    "caption": "updated",
                    "position": 1,
                }),
            )),
            LLMResponse(tool_calls=(ToolCall(
                id="detach", name="detach_item_photo", arguments={"media_id": media.id}
            ),)),
            LLMResponse(content="Updated."),
        ]),
    ).run("Recount, update the photo metadata, then detach it")

    assert [receipt.operation for receipt in run.receipts] == [
        "change_item_quantity", "update_item_photo", "detach_item_photo"
    ]
    assert (inventory.get_item(item.id).quantity_mode, inventory.get_item(item.id).quantity) == (
        "approximate", 4
    )
    assert inventory.list_item_photos(item.id) == []

    AgentRunner(
        session,
        ScriptedLLMClient([
            LLMResponse(tool_calls=(ToolCall(
                id="undo", name="undo_last_action", arguments={}
            ),)),
            LLMResponse(content="Undone."),
        ]),
    ).run("Undo", conversation_id=run.conversation_id)

    restored_item = inventory.get_item(item.id)
    restored_media = inventory.list_item_photos(item.id)
    assert (restored_item.quantity_mode, restored_item.quantity) == ("exact", 5)
    assert len(restored_media) == 1
    assert restored_media[0].id == media.id
    assert restored_media[0].provider == "local"
    assert restored_media[0].media_reference == "receipt-photo"
    assert restored_media[0].caption == "before"
    assert restored_media[0].position == 3
