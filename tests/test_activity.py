# test_activity.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import Event
from ah_there_it_is.services.activity import ActivityService
from ah_there_it_is.services.inventory import InventoryService


class _SessionContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *_args) -> None:
        return None


def _client(session: Session) -> TestClient:
    return TestClient(create_app(
        Settings(app_name="Activity Inventory"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    ))

def test_activity_filters_ties_pagination_and_unknown_ids(session: Session) -> None:
    item = InventoryService(session).create_item("Audit target")
    instant = datetime(2024, 1, 1, tzinfo=timezone.utc)
    session.add_all([
        Event(event_type="audit", item_id=item.id, created_at=instant, payload={"n": n})
        for n in range(3)
    ])
    session.commit()
    tie_ids = list(session.scalars(
        select(Event.id)
        .where(Event.event_type == "audit")
        .order_by(Event.id)
    ))
    service = ActivityService(session)
    first = service.page(event_type="audit", item_id=item.id, page_size=2)
    second = service.page(
        event_type="audit", item_id=item.id, page=2, page_size=2
    )
    assert first.total == 3 and first.pages == 2
    assert [row["id"] for row in first.items] == tie_ids[::-1][:2]
    assert first.next_page == 2 and first.has_next

    assert second.previous_page == 1 and not second.has_next
    assert [row["id"] for row in second.items] == tie_ids[:1]
    assert service.page(item_id=999999).total == 0

    with _client(session) as client:
        filtered = client.get("/activity", params={
            "event_type": "audit", "item_id": item.id, "page_size": 2,
        })
        empty = client.get("/activity", params={
            "event_type": "missing", "item_id": 999999,
        })
        too_large = client.get("/activity?page_size=101")
        bad_page = client.get("/activity?page=0")
        missing_event = client.get("/activity/999999")
    assert filtered.status_code == 200
    assert f'href="/activity?page=2&amp;page_size=2&amp;event_type=audit&amp;item_id={item.id}"' in filtered.text
    assert f'href="/activity/{tie_ids[-1]}"' in filtered.text
    assert 'href="/activity">Clear filters</a>' in filtered.text

    assert "Total: 0" in empty.text and "No matching Events." in empty.text
    assert too_large.status_code == 400
    assert bad_page.status_code == 400
    assert missing_event.status_code == 404


def test_activity_renders_historical_and_legacy_paths_safely(
    session: Session,
) -> None:
    inventory = InventoryService(session)
    room = inventory.create_location("Room")
    shelf = inventory.create_location("Shelf", parent_id=room.id)
    tools = inventory.create_category("Tools")
    adapter = inventory.create_category("Adapter", parent_id=tools.id)
    item = inventory.create_item(
        "USB adapter", location_id=shelf.id, category_id=adapter.id
    )
    created = inventory.get_item_history(item.id)[0]
    deleted_item = inventory.create_item("Deleted reference")
    deleted_event_id = inventory.get_item_history(deleted_item.id)[0].id
    session.delete(deleted_item)
    session.commit()

    inventory.update_location(room.id, name="Renamed room")
    inventory.update_category(tools.id, name="Updated tools")
    legacy = Event(
        event_type="legacy_move",
        item_id=item.id,
        from_location_id=shelf.id,
        to_location_id=shelf.id,
        payload={"legacy": True},
        original_text="old move",
    )
    orphan = Event(event_type="orphaned", item_id=None, payload={})
    session.add_all([legacy, orphan])
    session.commit()

    with _client(session) as client:
        historical = client.get(f"/activity/{created.id}")
        current_only = client.get(f"/activity/{legacy.id}")
        no_item = client.get(f"/activity/{orphan.id}")
        deleted_reference = client.get(f"/activity/{deleted_event_id}")
        item_detail = client.get(f"/items/{item.id}")

    assert historical.status_code == current_only.status_code == no_item.status_code == 200
    assert "Historical path at event time" in historical.text
    assert f'href="/items/{item.id}"' in historical.text
    assert f'href="/locations/{shelf.id}"' in historical.text
    assert "Event ID" in historical.text
    assert "Payload" in historical.text
    assert "Tools / Adapter" in historical.text
    assert "Renamed room / Shelf" not in historical.text
    assert "Current path; historical path unavailable" in current_only.text
    assert "Renamed room / Shelf" in current_only.text
    assert "Room / Shelf" not in current_only.text
    assert "No linked Item" in no_item.text
    assert 'href="/items/None"' not in no_item.text
    assert deleted_reference.status_code == 200
    assert "No linked Item" in deleted_reference.text
    assert 'href="/items/' not in deleted_reference.text
    assert "old move" in current_only.text
    assert f'href="/activity/{created.id}"' in item_detail.text
    assert "Historical path at event time" in item_detail.text
