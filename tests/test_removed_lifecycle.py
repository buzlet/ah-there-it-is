from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Event, Item
from ah_there_it_is.domain.exceptions import DuplicateEntityError
from ah_there_it_is.services import CatalogService, InventoryService


def test_remove_preserves_quantity_and_records_reason(session: Session) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    item = service.create_item(
        "Screws",
        state="used",
        location_id=shelf.id,
        quantity_mode="approximate",
        quantity=12,
    )

    removed = service.remove_item(
        item.id,
        reason="  отдал соседу  ",
        reason_source="explicit",
        original_text="Сними с учёта, отдал соседу",
    )

    assert removed.id == item.id
    assert (removed.quantity_mode, removed.quantity) == ("approximate", 12)
    assert removed.state == "removed"
    assert removed.removal_reason == "отдал соседу"
    assert removed.current_location_id is None
    assert removed.location_status == "not_applicable"
    event = service.get_item_history(item.id)[-1]
    assert event.event_type == "item_removed"
    assert event.payload["reason"] == "отдал соседу"
    assert event.payload["reason_source"] == "explicit"


def test_partial_remove_splits_and_removes_only_child(session: Session) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    source = service.create_item("Batteries", location_id=shelf.id, quantity=20)

    child = service.remove_item(
        source.id,
        portion={"mode": "exact", "value": 4},
        reason="использовал",
        reason_source="context",
    )

    assert (source.state, source.quantity) == ("unknown", 16)
    assert source.current_location_id == shelf.id
    assert (child.state, child.quantity) == ("removed", 4)
    assert child.removal_reason == "использовал"
    assert child.id != source.id


def test_restore_keeps_stable_id_and_clears_reason(session: Session) -> None:
    service = InventoryService(session)
    shelf = service.create_location("Shelf")
    item = service.create_item("Adapter", state="used")
    service.remove_item(
        item.id,
        reason="больше не нужен",
        reason_source="explicit",
    )

    restored = service.restore_item(
        item.id,
        state="working",
        location_id=shelf.id,
        original_text="Верни адаптер на полку",
    )

    assert restored.id == item.id
    assert restored.state == "working"
    assert restored.current_location_id == shelf.id
    assert restored.location_status == "known"
    assert restored.removal_reason is None
    event = service.get_item_history(item.id)[-1]
    assert event.event_type == "item_restored"
    assert event.payload["removal_reason"] == {
        "from": "больше не нужен",
        "to": None,
    }


def test_equivalent_lots_require_explicit_intent_but_split_is_allowed(
    session: Session,
) -> None:
    service = InventoryService(session)
    first = service.create_item("Cable")
    with pytest.raises(DuplicateEntityError):
        service.create_item(" cable ")
    second = service.create_item("Cable", allow_duplicate=True)

    assert first.id != second.id
    assert session.scalar(select(func.count(Item.id))) == 2


def test_catalog_lifecycle_filters_removed(session: Session) -> None:
    service = InventoryService(session)
    active = service.create_item("Active")
    removed = service.create_item("Removed")
    service.remove_item(
        removed.id, reason="stop tracking", reason_source="explicit"
    )
    catalog = CatalogService(session)

    assert [item["id"] for item in catalog.item_page(lifecycle="active").items] == [
        active.id
    ]
    assert [item["id"] for item in catalog.item_page(lifecycle="terminal").items] == [
        removed.id
    ]


def test_partial_remove_failure_rolls_back_everything(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = InventoryService(session)
    source = service.create_item("Clips", quantity=10)
    before_events = session.scalar(select(func.count(Event.id)))

    def fail_transition(*_args, **_kwargs):
        raise RuntimeError("injected remove failure")

    monkeypatch.setattr(service, "_record_location_transition", fail_transition)
    with pytest.raises(RuntimeError, match="injected"):
        service.remove_item(
            source.id,
            portion={"mode": "exact", "value": 3},
            reason="gave away",
            reason_source="explicit",
        )

    session.expire_all()
    restored = service.get_item(source.id)
    assert (restored.state, restored.quantity) == ("unknown", 10)
    assert session.scalar(select(func.count(Item.id))) == 1
    assert session.scalar(select(func.count(Event.id))) == before_events


def test_legacy_lifecycle_shims_map_to_removed(session: Session) -> None:
    service = InventoryService(session)
    sold = service.create_item("Sold")
    discarded = service.create_item("Discarded")

    service.mark_item_sold(sold.id)
    service.discard_item(discarded.id)

    assert (sold.state, sold.removal_reason) == ("removed", "sold")
    assert (discarded.state, discarded.removal_reason) == ("removed", "discarded")
