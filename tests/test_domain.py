from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from ah_there_it_is.domain.exceptions import DuplicateEntityError, EntityNotFoundError
from ah_there_it_is.domain.names import normalize_name
from ah_there_it_is.domain.states import ItemState
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
    service.move_item(item.id, None, original_text="Достал переходник")

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
