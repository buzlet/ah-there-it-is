# test_bounded_reads.py
"""Page bounds and capability scope for high-cardinality request reads."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent.experiments import CapturedEvidenceReplay
from ah_there_it_is.agent.tools import ToolDispatcher, ToolRunState
from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import Event, Item
from ah_there_it_is.services.inventory import InventoryService


class _SessionContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *_args) -> None:
        return None


@contextmanager
def loaded_entities(session: Session):
    loaded: list[object] = []
    statements: list[str] = []
    def on_load(_session, instance):
        if isinstance(instance, (Event, Item)):
            loaded.append(instance)
    def on_statement(_connection, _cursor, statement, *_args):
        statements.append(statement)
    event.listen(session, "loaded_as_persistent", on_load)
    event.listen(session.get_bind(), "before_cursor_execute", on_statement)
    try:
        yield loaded, statements
    finally:
        event.remove(session, "loaded_as_persistent", on_load)
        event.remove(session.get_bind(), "before_cursor_execute", on_statement)


def seed_large_reads(session: Session) -> tuple[int, int]:
    inventory = InventoryService(session)
    location = inventory.create_location("Bulk shelf")
    item = inventory.create_item("History target", location_id=location.id)
    instant = datetime(2020, 1, 1, tzinfo=timezone.utc)
    session.execute(Event.__table__.insert(), [
        {"event_type": "audit_event", "item_id": item.id,
         "created_at": instant, "payload": {"n": n}}
        for n in range(1000)
    ])
    session.execute(Item.__table__.insert(), [
        {"name": f"Bulk item {n:04}", "normalized_name": f"bulk item {n:04}",
         "current_location_id": location.id, "state": "unknown", "quantity": 1,
         "attributes": {}}
        for n in range(350)
    ])
    session.commit()
    session.expunge_all()
    return item.id, location.id


def test_service_pages_have_stable_order_and_bounded_materialization(session: Session) -> None:
    item_id, location_id = seed_large_reads(session)
    inventory = InventoryService(session)
    with loaded_entities(session) as (loaded, statements):
        history = inventory.get_item_history_page(item_id, page=2, page_size=37)
    assert history.total == 1001
    assert history.pages == 28
    assert len(history.items) == 37
    assert history.previous_page == 1 and history.next_page == 3
    assert sum(isinstance(value, Event) for value in loaded) <= 37
    assert len(statements) <= 4
    assert any("LIMIT" in sql.upper() for sql in statements)
    expected = list(session.scalars(
        select(Event.id).where(Event.item_id == item_id)
        .order_by(Event.created_at, Event.id).offset(37).limit(37)
    ))
    assert [row.id for row in history.items] == expected

    session.expunge_all()
    with loaded_entities(session) as (loaded, statements):
        location = inventory.list_location_page(location_id, page=3, page_size=40)
    assert location.total == 351
    assert location.pages == 9
    assert len(location.items) == 40
    assert [row.id for row in location.items] == sorted(row.id for row in location.items)
    assert sum(isinstance(value, Item) for value in loaded) <= 40
    assert len(statements) <= 9
    assert any("LIMIT" in sql.upper() for sql in statements)
    assert [row.id for row in location.items] == list(session.scalars(
        select(Item.id).where(Item.current_location_id == location_id)
        .order_by(Item.id).offset(80).limit(40)
    ))


@pytest.mark.parametrize("page,page_size", [(0, 50), (-1, 50), (1, 0), (1, 101)])
def test_service_rejects_invalid_page_inputs(session: Session, page: int, page_size: int) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Meter")
    location = inventory.create_location("Shelf")
    with pytest.raises(ValueError):
        inventory.get_item_history_page(item.id, page=page, page_size=page_size)
    with pytest.raises(ValueError):
        inventory.list_location_page(location.id, page=page, page_size=page_size)


def test_tool_pages_limit_seen_capabilities_and_replay(session: Session) -> None:
    item_id, location_id = seed_large_reads(session)
    state = ToolRunState()
    state.seen["location"].add(location_id)
    state.seen["item"].add(item_id)
    dispatcher = ToolDispatcher(session, state=state)
    schema = {definition.name: definition.input_schema for definition in dispatcher.definitions()}
    for name in ("list_location", "get_item_history"):
        assert schema[name]["properties"]["page"]["minimum"] == 1
        assert schema[name]["properties"]["page_size"]["maximum"] == 100

    with loaded_entities(session) as (loaded, statements):
        first = dispatcher.execute("list_location", {"location_id": location_id, "page_size": 25})
    assert first["ok"] is True
    assert first["result"]["total"] == 351
    assert len(first["result"]["items"]) == 25
    assert first["result"]["next_page"] == 2
    assert sum(isinstance(value, Item) for value in loaded) <= 25
    assert len(statements) <= 10
    returned_ids = {row["id"] for row in first["result"]["items"]}
    assert state.seen["item"] == returned_ids | {item_id}
    replay_state = ToolRunState()
    CapturedEvidenceReplay.observe_capabilities(
        replay_state, "list_location", {"location_id": location_id}, first,
    )
    assert replay_state.seen["item"] == returned_ids

    session.expunge_all()
    with loaded_entities(session) as (loaded, statements):
        history = dispatcher.execute("get_item_history", {"item_id": item_id, "page": 10})
    assert history["ok"] is True
    assert history["result"]["total"] == 1001
    assert len(history["result"]["items"]) == 50
    assert history["result"]["page"] == 10
    assert sum(isinstance(value, Event) for value in loaded) <= 50
    assert len(statements) <= 4
    for name, args in (
        ("list_location", {"location_id": location_id, "page": 0}),
        ("get_item_history", {"item_id": item_id, "page_size": 101}),
    ):
        assert dispatcher.execute(name, args)["error"]["type"] == "invalid_arguments"
    beyond = dispatcher.execute("list_location", {"location_id": location_id, "page": 100})
    assert beyond["result"]["items"] == []
    assert beyond["result"]["total"] == 351
    assert beyond["result"]["next_page"] is None


def test_item_browser_history_has_page_links_without_loading_all_events(session: Session) -> None:
    item_id, _ = seed_large_reads(session)
    app = create_app(
        Settings(app_name="Bounded Inventory"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        session.expunge_all()
        with loaded_entities(session) as (loaded, statements):
            first = client.get(f"/items/{item_id}")
        assert first.status_code == 200
        assert first.text.count("audit_event") <= 50
        assert 'Next history page' in first.text
        assert f'/items/{item_id}?page=2&amp;page_size=50' in first.text
        assert sum(isinstance(value, Event) for value in loaded) <= 50
        assert len(statements) < 100
        second = client.get(f"/items/{item_id}?page=2&page_size=25")
        assert second.status_code == 200
        assert f'/items/{item_id}?page=1&amp;page_size=25' in second.text
        assert f'/items/{item_id}?page=3&amp;page_size=25' in second.text
        assert second.text.count("audit_event") == 25
        assert client.get(f"/items/{item_id}?page=0").status_code == 400
        assert client.get(f"/items/{item_id}?page_size=101").status_code == 400
        outside = client.get(f"/items/{item_id}?page=999")
        assert outside.status_code == 200
        assert "No history." in outside.text
        assert "Total: 1001" in outside.text
