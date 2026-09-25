from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Event, Item
from ah_there_it_is.services import InventoryService


def test_partial_move_splits_exact_lot_and_preserves_source_id(session: Session) -> None:
    service = InventoryService(session)
    workshop = service.create_location("Workshop")
    backpack = service.create_location("Backpack")
    source = service.create_item(
        "Screws",
        description="zinc screws",
        state="used",
        location_id=workshop.id,
        quantity=20,
        aliases=["fasteners"],
        tags=["hardware"],
        attributes={"size": "M4"},
    )
    source_id = source.id

    child = service.move_item(
        source.id,
        backpack.id,
        portion={"mode": "exact", "value": 5},
        original_text="Перемести 5 винтов в рюкзак",
    )

    source = service.get_item(source_id)
    assert child.id != source_id
    assert (source.quantity_mode, source.quantity) == ("exact", 15)
    assert (child.quantity_mode, child.quantity) == ("exact", 5)
    assert source.current_location_id == workshop.id
    assert child.current_location_id == backpack.id
    assert child.description == source.description
    assert child.attributes == source.attributes
    assert [alias.name for alias in child.aliases] == ["fasteners"]
    assert [link.tag.name for link in child.tag_links] == ["hardware"]
    assert [event.event_type for event in service.get_item_history(source.id)][-1] == "item_split"
    assert [event.event_type for event in service.get_item_history(child.id)][-2:] == [
        "item_split_from",
        "item_moved",
    ]


@pytest.mark.parametrize(
    ("source_mode", "source_value", "child_mode", "child_value", "remainder"),
    [
        ("approximate", 20, "exact", 5, ("approximate", 15)),
        ("approximate", 20, "approximate", 5, ("approximate", 15)),
        ("unknown", None, "exact", 5, ("unknown", None)),
        ("unknown", None, "unknown", None, ("unknown", None)),
        ("approximate", 5, "exact", 7, ("unknown", None)),
        ("exact", 5, "exact", 7, ("unknown", None)),
        ("exact", 20, "unknown", None, ("unknown", None)),
    ],
)
def test_partial_take_quantity_arithmetic(
    session: Session,
    source_mode: str,
    source_value: int | None,
    child_mode: str,
    child_value: int | None,
    remainder: tuple[str, int | None],
) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    source = service.create_item(
        "Batteries",
        location_id=shelf.id,
        quantity_mode=source_mode,
        quantity=source_value,
    )

    child = service.take_item(
        source.id,
        portion={"mode": child_mode, "value": child_value},
    )

    assert (source.quantity_mode, source.quantity) == remainder
    assert (child.quantity_mode, child.quantity) == (child_mode, child_value)
    assert child.location_status == "in_use"
    assert source.current_location_id == shelf.id


def test_exact_full_portion_preserves_id_without_split(session: Session) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    drawer = service.create_location("Drawer")
    item = service.create_item("Washers", location_id=shelf.id, quantity=5)

    moved = service.move_item(
        item.id, drawer.id, portion={"mode": "exact", "value": 5}
    )

    assert moved.id == item.id
    assert session.scalar(select(func.count(Item.id))) == 1
    assert not any(
        event.event_type.startswith("item_split")
        for event in service.get_item_history(item.id)
    )


def test_partial_move_failure_rolls_back_source_child_and_events(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    drawer = service.create_location("Drawer")
    source = service.create_item("Nuts", location_id=shelf.id, quantity=10)
    before_events = session.scalar(select(func.count(Event.id)))

    def fail_transition(*_args, **_kwargs):
        raise RuntimeError("injected move failure")

    monkeypatch.setattr(service, "_record_location_transition", fail_transition)
    with pytest.raises(RuntimeError, match="injected"):
        service.move_item(
            source.id,
            drawer.id,
            portion={"mode": "exact", "value": 3},
        )

    session.expire_all()
    restored = service.get_item(source.id)
    assert (restored.quantity_mode, restored.quantity) == ("exact", 10)
    assert session.scalar(select(func.count(Item.id))) == 1
    assert session.scalar(select(func.count(Event.id))) == before_events


def test_partial_same_destination_is_noop_without_split(session: Session) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    source = service.create_item("Clips", location_id=shelf.id, quantity=10)

    result = service.move_item(
        source.id, shelf.id, portion={"mode": "exact", "value": 2}
    )

    assert result.id == source.id
    assert (source.quantity_mode, source.quantity) == ("exact", 10)
    assert session.scalar(select(func.count(Item.id))) == 1
