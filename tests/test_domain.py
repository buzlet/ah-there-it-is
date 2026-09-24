from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Event
from ah_there_it_is.domain.exceptions import DuplicateEntityError, EntityNotFoundError
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.states import ItemState, LocationStatus
from ah_there_it_is.services import InventoryService


def test_name_normalization() -> None:
    assert normalize_name("  Блок   Питания  ") == "блок питания"
    assert normalize_name("ＡＳＵＳ") == "asus"


def test_create_tree_item_and_history(session: Session) -> None:
    service = InventoryService(session)
    balcony = service.create_location("Балкон")
    shelf = service.create_location("Полка 1", parent_id=balcony.id)
    computers = service.create_category("Компьютеры")
    psus = service.create_category("Блоки питания", parent_id=computers.id)

    item = service.create_item(
        "Chieftec 750W",
        description="Старый блок питания; напряжение нужно проверить.",
        state=ItemState.NEEDS_TEST,
        category_id=psus.id,
        location_id=shelf.id,
        attributes={"power_w": 750, "manufacturer": "Chieftec"},
        aliases=["Chieftec PSU", " chieftec   psu "],
        tags=["ATX", "computer", "atx"],
        original_text="Положил Chieftec 750 ватт на первую полку балкона.",
    )

    assert item.current_location_id == shelf.id
    assert item.category_id == psus.id
    assert item.attributes["power_w"] == 750
    assert [alias.normalized_name for alias in item.aliases] == ["chieftec psu"]
    assert sorted(link.tag.normalized_name for link in item.tag_links) == ["atx", "computer"]

    history = service.get_item_history(item.id)
    assert [event.event_type for event in history] == ["item_created"]
    assert history[0].to_location_id == shelf.id
    assert history[0].original_text is not None


def test_move_item_preserves_history(session: Session) -> None:
    service = InventoryService(session)
    desk = service.create_location("Стол")
    drawer = service.create_location("Нижний ящик", parent_id=desk.id)
    balcony = service.create_location("Балкон")
    item = service.create_item("USB-SATA adapter", location_id=drawer.id)

    service.move_item(item.id, balcony.id, original_text="Переложил переходник на балкон")
    service.take_item(item.id, original_text="Достал переходник")

    assert item.current_location_id is None
    history = service.get_item_history(item.id)
    assert [event.event_type for event in history] == [
        "item_created",
        "item_moved",
        "item_taken",
    ]
    assert history[1].from_location_id == drawer.id
    assert history[1].to_location_id == balcony.id
    assert history[2].from_location_id == balcony.id
    assert history[2].to_location_id is None


def test_update_item_records_material_change(session: Session) -> None:
    service = InventoryService(session)
    item = service.create_item("DT-830B", state=ItemState.UNKNOWN)

    service.update_item(
        item.id,
        state=ItemState.BROKEN,
        description="Щупы повреждены.",
        attributes={"color": "red"},
        original_text="Красный мультиметр неисправен, щупы повреждены.",
    )

    history = service.get_item_history(item.id)
    assert [event.event_type for event in history] == ["item_created", "item_updated"]
    assert history[-1].payload["state"]["to"] == "broken"
    assert item.attributes == {"color": "red"}



def test_location_transitions_are_explicit_and_noop_safe(session: Session) -> None:
    service = InventoryService(session)
    room = service.create_location("Room")
    shelf = service.create_location("Shelf", parent_id=room.id)
    item = service.create_item("Probe", location_id=shelf.id)

    service.take_item(item.id)
    assert item.current_location_id is None
    assert item.location_status == LocationStatus.IN_USE.value
    taken = service.get_item_history(item.id)[-1]
    assert taken.event_type == "item_taken"
    assert taken.from_location_id == shelf.id
    assert taken.to_location_id is None
    assert taken.payload["_history_evidence"] == {
        "version": 1,
        "from_location_path": [
            {"location_id": room.id, "name": "Room"},
            {"location_id": shelf.id, "name": "Shelf"},
        ],
    }
    event_count = len(service.get_item_history(item.id))
    service.take_item(item.id)
    assert len(service.get_item_history(item.id)) == event_count

    service.mark_item_location_unknown(item.id)
    assert item.location_status == LocationStatus.UNKNOWN.value
    unknown = service.get_item_history(item.id)[-1]
    assert unknown.event_type == "item_location_unknown"
    assert unknown.payload["_history_evidence"] == {"version": 1}
    event_count = len(service.get_item_history(item.id))
    service.mark_item_location_unknown(item.id)
    assert len(service.get_item_history(item.id)) == event_count

    service.move_item(item.id, shelf.id)
    assert item.current_location_id == shelf.id
    assert item.location_status == LocationStatus.KNOWN.value
    moved = service.get_item_history(item.id)[-1]
    assert moved.event_type == "item_moved"
    assert moved.from_location_id is None
    assert moved.to_location_id == shelf.id
    assert moved.payload["_history_evidence"]["to_location_path"] == [
        {"location_id": room.id, "name": "Room"},
        {"location_id": shelf.id, "name": "Shelf"},
    ]
    with pytest.raises(ValueError, match="requires a Location"):
        service.move_item(item.id, None)  # type: ignore[arg-type]
    service.mark_item_location_unknown(item.id)
    unknown_from_known = service.get_item_history(item.id)[-1]
    assert unknown_from_known.event_type == "item_location_unknown"
    assert unknown_from_known.from_location_id == shelf.id
    assert unknown_from_known.to_location_id is None
    assert unknown_from_known.payload["_history_evidence"]["from_location_path"] == [
        {"location_id": room.id, "name": "Room"},
        {"location_id": shelf.id, "name": "Shelf"},
    ]


def test_terminal_transitions_and_reactivation_are_atomic_and_explicit(
    session: Session,
) -> None:
    service = InventoryService(session)
    room = service.create_location("Room")
    shelf = service.create_location("Shelf", parent_id=room.id)
    item = service.create_item("Probe", state=ItemState.WORKING, location_id=shelf.id)

    service.discard_item(item.id)
    assert item.state == ItemState.DISCARDED.value
    assert item.current_location_id is None
    assert item.location_status == LocationStatus.NOT_APPLICABLE.value
    discarded = service.get_item_history(item.id)[-1]
    assert discarded.event_type == "item_discarded"
    assert discarded.from_location_id == shelf.id
    assert discarded.to_location_id is None
    assert discarded.payload["state"] == {"from": "working", "to": "discarded"}
    assert discarded.payload["location_status"] == {
        "from": "known", "to": "not_applicable"
    }
    assert discarded.payload["_history_evidence"]["from_location_path"] == [
        {"location_id": room.id, "name": "Room"},
        {"location_id": shelf.id, "name": "Shelf"},
    ]
    event_count = len(service.get_item_history(item.id))
    service.discard_item(item.id)
    assert len(service.get_item_history(item.id)) == event_count
    with pytest.raises(ValueError, match="another terminal transition"):
        service.mark_item_sold(item.id)
    with pytest.raises(ValueError, match="terminal state changes"):
        service.update_item(item.id, state=ItemState.WORKING)
    with pytest.raises(ValueError, match="terminal state changes"):
        service.update_item(item.id, state=ItemState.SOLD)
    service.update_item(item.id, state=ItemState.DISCARDED)
    still_discarded = service.create_item("Other probe", state=ItemState.WORKING)
    with pytest.raises(ValueError, match="discard transitions"):
        service.update_item(still_discarded.id, state=ItemState.DISCARDED)
    assert still_discarded.state == ItemState.WORKING.value

    service.reactivate_item(item.id, state=ItemState.USED, location_id=None)
    assert item.state == ItemState.USED.value
    assert item.current_location_id is None
    assert item.location_status == LocationStatus.UNKNOWN.value
    reactivated_unknown = service.get_item_history(item.id)[-1]
    assert reactivated_unknown.event_type == "item_reactivated"
    assert reactivated_unknown.from_location_id is None
    assert reactivated_unknown.to_location_id is None
    assert reactivated_unknown.payload["state"] == {"from": "discarded", "to": "used"}
    assert reactivated_unknown.payload["location_status"] == {
        "from": "not_applicable", "to": "unknown"
    }
    with pytest.raises(ValueError, match="only sold or discarded"):
        service.reactivate_item(item.id, state=ItemState.WORKING, location_id=shelf.id)

    service.mark_item_sold(item.id)
    assert item.state == ItemState.SOLD.value
    assert item.location_status == LocationStatus.NOT_APPLICABLE.value
    sold = service.get_item_history(item.id)[-1]
    assert sold.event_type == "item_sold"
    assert sold.payload["state"] == {"from": "used", "to": "sold"}
    assert sold.payload["location_status"] == {
        "from": "unknown", "to": "not_applicable"
    }
    with pytest.raises(ValueError, match="invalid item state"):
        service.reactivate_item(item.id, state="in_use", location_id=None)
    service.reactivate_item(item.id, state=ItemState.NEEDS_TEST, location_id=shelf.id)
    assert item.state == ItemState.NEEDS_TEST.value
    assert item.current_location_id == shelf.id
    assert item.location_status == LocationStatus.KNOWN.value
    reactivated_known = service.get_item_history(item.id)[-1]
    assert reactivated_known.event_type == "item_reactivated"
    assert reactivated_known.to_location_id == shelf.id
    assert reactivated_known.payload["_history_evidence"]["to_location_path"] == [
        {"location_id": room.id, "name": "Room"},
        {"location_id": shelf.id, "name": "Shelf"},
    ]


def test_duplicate_tree_nodes_are_rejected_even_at_root(session: Session) -> None:
    service = InventoryService(session)
    service.create_location("Балкон")
    service.create_category("Электроника")

    with pytest.raises(DuplicateEntityError):
        service.create_location("  БАЛКОН ")
    with pytest.raises(DuplicateEntityError):
        service.create_category("электроника")


def test_item_duplicate_requires_explicit_override(session: Session) -> None:
    service = InventoryService(session)
    category = service.create_category("Кабели")
    service.create_item("HDMI cable", category_id=category.id)

    with pytest.raises(DuplicateEntityError):
        service.create_item("  hdmi   CABLE ", category_id=category.id)

    second = service.create_item(
        "HDMI cable", category_id=category.id, allow_duplicate=True
    )
    assert second.id is not None


def test_missing_ids_and_invalid_state_fail_without_partial_write(session: Session) -> None:
    service = InventoryService(session)

    with pytest.raises(EntityNotFoundError):
        service.create_item("Thing", location_id=999)
    with pytest.raises(ValueError):
        service.create_item("Thing", state="slightly_suspicious")

    assert session.scalar(text("SELECT count(*) FROM items")) == 0


def test_sqlite_foreign_keys_are_enabled(session: Session) -> None:
    assert session.scalar(text("PRAGMA foreign_keys")) == 1


def test_update_can_clear_optional_fields_and_noop_does_not_add_event(session: Session) -> None:
    service = InventoryService(session)
    category = service.create_category("Электроника")
    item = service.create_item(
        "Adapter",
        description="temporary note",
        category_id=category.id,
        aliases=["dongle"],
        tags=["USB"],
    )

    service.update_item(item.id, aliases=[" DONGLE "], tags=["usb"])
    assert len(service.get_item_history(item.id)) == 1

    service.update_item(item.id, description=None, category_id=None)
    assert item.description is None
    assert item.category_id is None
    assert len(service.get_item_history(item.id)) == 2


def test_failed_update_does_not_dirty_item(session: Session) -> None:
    service = InventoryService(session)
    item = service.create_item("Original")

    with pytest.raises(EntityNotFoundError):
        service.update_item(item.id, name="Mutated", category_id=999)

    assert item.name == "Original"
    assert session.get(type(item), item.id).name == "Original"


def test_duplicate_name_is_allowed_under_different_tree_parents(session: Session) -> None:
    service = InventoryService(session)
    desk = service.create_location("Стол")
    cabinet = service.create_location("Шкаф")

    desk_drawer = service.create_location("Ящик", parent_id=desk.id)
    cabinet_drawer = service.create_location("Ящик", parent_id=cabinet.id)

    assert desk_drawer.id != cabinet_drawer.id


def test_event_history_evidence_is_immutable_across_tree_changes(session: Session) -> None:
    service = InventoryService(session)
    home = service.create_location("Home")
    room = service.create_location("Room", parent_id=home.id)
    shelf = service.create_location("Shelf", parent_id=room.id)
    office = service.create_location("Office")
    desk = service.create_location("Desk", parent_id=office.id)
    drawer = service.create_location("Drawer", parent_id=desk.id)

    tools = service.create_category("Tools")
    adapters = service.create_category("Adapters", parent_id=tools.id)
    electronics = service.create_category("Electronics")
    components = service.create_category("Components", parent_id=electronics.id)

    item = service.create_item(
        "USB adapter", location_id=shelf.id, category_id=adapters.id
    )
    (created,) = service.get_item_history(item.id)
    original_home_path = [
        {"location_id": home.id, "name": "Home"},
        {"location_id": room.id, "name": "Room"},
        {"location_id": shelf.id, "name": "Shelf"},
    ]
    original_adapter_path = [
        {"category_id": tools.id, "name": "Tools"},
        {"category_id": adapters.id, "name": "Adapters"},
    ]
    assert created.payload == {
        "name": "USB adapter",
        "quantity": 1,
        "_history_evidence": {
            "version": 1,
            "to_location_path": original_home_path,
            "to_category_path": original_adapter_path,
        },
    }

    service.move_item(item.id, drawer.id)
    service.update_item(item.id, category_id=components.id)
    created, moved, updated = service.get_item_history(item.id)
    original_office_path = [
        {"location_id": office.id, "name": "Office"},
        {"location_id": desk.id, "name": "Desk"},
        {"location_id": drawer.id, "name": "Drawer"},
    ]
    original_component_path = [
        {"category_id": electronics.id, "name": "Electronics"},
        {"category_id": components.id, "name": "Components"},
    ]
    assert moved.payload == {
        "_history_evidence": {
            "version": 1,
            "from_location_path": original_home_path,
            "to_location_path": original_office_path,
        }
    }
    assert updated.payload["category_id"] == {
        "from": adapters.id,
        "to": components.id,
    }
    assert updated.payload["_history_evidence"] == {
        "version": 1,
        "from_category_path": original_adapter_path,
        "to_category_path": original_component_path,
    }
    evidence_before_tree_changes = {
        event.id: event.payload["_history_evidence"] for event in (created, moved, updated)
    }

    archive = service.create_location("Archive")
    service.update_location(home.id, name="Old home", parent_id=archive.id)
    service.update_location(office.id, name="Old office", parent_id=archive.id)
    other = service.create_category("Other")
    service.update_category(tools.id, name="Old tools", parent_id=other.id)
    service.update_category(electronics.id, name="Old electronics", parent_id=other.id)

    history_after_tree_changes = service.get_item_history(item.id)
    assert len(history_after_tree_changes) == 3
    assert {
        event.id: event.payload["_history_evidence"]
        for event in history_after_tree_changes
    } == evidence_before_tree_changes


def test_event_history_evidence_omits_null_paths_and_keeps_legacy_events(
    session: Session,
) -> None:
    service = InventoryService(session)
    item = service.create_item("Unlocated item")
    (created,) = service.get_item_history(item.id)
    assert created.payload["_history_evidence"] == {"version": 1}

    room = service.create_location("Room")
    shelf = service.create_location("Shelf", parent_id=room.id)
    service.move_item(item.id, shelf.id)
    _, moved = service.get_item_history(item.id)
    assert moved.payload["_history_evidence"] == {
        "version": 1,
        "to_location_path": [
            {"location_id": room.id, "name": "Room"},
            {"location_id": shelf.id, "name": "Shelf"},
        ],
    }

    service.take_item(item.id)
    _, _, taken = service.get_item_history(item.id)
    assert taken.event_type == "item_taken"
    assert taken.payload["_history_evidence"] == {
        "version": 1,
        "from_location_path": [
            {"location_id": room.id, "name": "Room"},
            {"location_id": shelf.id, "name": "Shelf"},
        ],
    }

    tools = service.create_category("Tools")
    adapters = service.create_category("Adapters", parent_id=tools.id)
    service.update_item(item.id, category_id=adapters.id)
    category_added = service.get_item_history(item.id)[-1]
    assert category_added.payload["_history_evidence"] == {
        "version": 1,
        "to_category_path": [
            {"category_id": tools.id, "name": "Tools"},
            {"category_id": adapters.id, "name": "Adapters"},
        ],
    }

    service.update_item(item.id, category_id=None)
    category_cleared = service.get_item_history(item.id)[-1]
    assert category_cleared.payload["_history_evidence"] == {
        "version": 1,
        "from_category_path": [
            {"category_id": tools.id, "name": "Tools"},
            {"category_id": adapters.id, "name": "Adapters"},
        ],
    }

    service.update_item(item.id, quantity=2)
    ordinary_update = service.get_item_history(item.id)[-1]
    assert "_history_evidence" not in ordinary_update.payload

    legacy_payload = {"quantity": {"from": 2, "to": 3}}
    legacy = Event(
        event_type="item_updated",
        item_id=item.id,
        payload=legacy_payload,
    )
    session.add(legacy)
    session.commit()
    legacy_event = next(
        event for event in service.get_item_history(item.id) if event.id == legacy.id
    )
    assert legacy_event.payload == legacy_payload



def test_location_truth_is_set_on_creation_and_existing_writes(session: Session) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    unknown = service.create_item("Unknown item")
    known = service.create_item("Known item", location_id=shelf.id)
    discarded = service.create_item(
        "Discarded item", state=ItemState.DISCARDED
    )
    sold = service.create_item("Imported sold item", state=ItemState.SOLD)

    assert unknown.location_status == LocationStatus.UNKNOWN.value
    assert known.location_status == LocationStatus.KNOWN.value
    assert discarded.location_status == LocationStatus.NOT_APPLICABLE.value
    assert sold.location_status == LocationStatus.NOT_APPLICABLE.value

    service.take_item(known.id)
    assert known.location_status == LocationStatus.IN_USE.value
    with pytest.raises(ValueError, match="terminal items cannot be moved"):
        service.move_item(discarded.id, shelf.id)
    with pytest.raises(ValueError, match="terminal state changes"):
        service.update_item(discarded.id, state=ItemState.WORKING)
    with pytest.raises(ValueError, match="sold transitions"):
        service.update_item(unknown.id, state=ItemState.SOLD)
