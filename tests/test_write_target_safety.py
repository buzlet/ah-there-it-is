# test_write_target_safety.py
"""Adversarial agent write authorization and stale-evidence checks."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.db.models import Base, Event
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.inventory import InventoryService


def _events(session: Session) -> int:
    return int(session.scalar(select(func.count(Event.id))) or 0)


def test_limit_one_hides_duplicate_identity_but_never_authorizes_write(session: Session) -> None:
    inventory = InventoryService(session)
    first = inventory.create_item("Meter")
    inventory.create_item("Meter", allow_duplicate=True)
    dispatcher = ToolDispatcher(session)

    result = dispatcher.execute("search_items", {"query": "Meter", "limit": 1})
    assert [row["id"] for row in result["result"]] == [first.id]
    assert first.id in dispatcher.state.seen["item"]
    assert first.id not in dispatcher.state.resolved["item"]
    before = _events(session)
    rejected = dispatcher.execute("change_item_quantity", {
        "item_id": first.id, "quantity_mode": "exact", "quantity": 2,
        "reason": "recount", "reason_source": "explicit",
    })
    assert rejected["error"]["type"] == "ToolPreconditionError"
    assert inventory.get_item(first.id).quantity == 1
    assert _events(session) == before


@pytest.mark.parametrize("collision", ["canonical_alias", "alias_alias"])
def test_cross_item_identity_collision_is_ambiguous(session: Session, collision: str) -> None:
    inventory = InventoryService(session)
    first = inventory.create_item("Meter", aliases=["Shared"])
    if collision == "canonical_alias":
        inventory.create_item("Shared")
    else:
        inventory.create_item("Other", aliases=["Shared"])
    location = inventory.create_location("Desk")
    dispatcher = ToolDispatcher(session)

    result = dispatcher.execute("search_items", {"query": "Shared", "limit": 1})
    assert result["result"]
    assert not dispatcher.state.resolved["item"]
    dispatcher.execute("search_locations", {"query": "Desk"})
    before = _events(session)
    rejected = dispatcher.execute(
        "move_item", {"item_id": first.id, "location_id": location.id}
    )
    assert rejected["error"]["type"] == "ToolPreconditionError"
    assert _events(session) == before


@pytest.mark.parametrize("query", ["serial-xyz", "rare-tag", "gadget", "socket", "plaid"])
def test_weak_singleton_item_evidence_is_read_only(session: Session, query: str) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item(
        "Gadget socket", description="mysterious plaid",
        attributes={"serial": "serial-xyz"}, tags=["rare-tag"]
    )
    dispatcher = ToolDispatcher(session)

    result = dispatcher.execute("search_items", {"query": query, "limit": 1})
    assert [row["id"] for row in result["result"]] == [item.id]
    assert item.id in dispatcher.state.seen["item"]
    assert item.id not in dispatcher.state.resolved["item"]
    assert dispatcher.execute("update_item", {"item_id": item.id, "quantity": 2})["ok"] is False


@pytest.mark.parametrize("entity", ["location", "category"])
def test_duplicate_tree_leaves_require_exact_full_path(session: Session, entity: str) -> None:
    inventory = InventoryService(session)
    create = inventory.create_location if entity == "location" else inventory.create_category
    left = create("Left")
    right = create("Right")
    leaf = create("Shelf", parent_id=left.id)
    create("Shelf", parent_id=right.id)
    dispatcher = ToolDispatcher(session)

    found = dispatcher.execute("search_categories" if entity == "category" else "search_locations", {"query": "Shelf", "limit": 1})
    assert len(found["result"]) == 1
    assert leaf.id not in dispatcher.state.resolved[entity]
    full = dispatcher.execute("search_categories" if entity == "category" else "search_locations", {"query": "Left / Shelf"})
    assert any(row["id"] == leaf.id for row in full["result"])
    assert leaf.id in dispatcher.state.resolved[entity]


def test_move_requires_location_and_take_is_explicit(session: Session) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Desk")
    item = inventory.create_item("Meter", location_id=location.id)
    dispatcher = ToolDispatcher(session)
    dispatcher.execute("search_items", {"query": "Meter"})
    before = _events(session)

    omitted = dispatcher.execute("move_item", {"item_id": item.id})
    assert omitted["error"]["type"] == "invalid_arguments"
    null_target = dispatcher.execute(
        "move_item", {"item_id": item.id, "location_id": None}
    )
    assert null_target["error"]["type"] == "invalid_arguments"
    assert inventory.get_item(item.id).current_location_id == location.id
    assert _events(session) == before

    taken = dispatcher.execute("take_item", {"item_id": item.id})
    assert taken["ok"] is True
    assert taken["result"]["location_status"] == "in_use"
    assert inventory.get_item(item.id).current_location_id is None
    assert _events(session) == before + 1


def test_item_identity_change_and_new_collision_reject_stale_write(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Meter")
    location = inventory.create_location("Desk")
    dispatcher = ToolDispatcher(session)
    dispatcher.execute("search_items", {"query": "Meter"})
    inventory.update_item(item.id, name="Renamed")
    before = _events(session)
    result = dispatcher.execute(
        "update_item", {"item_id": item.id, "description": "recounted"}
    )
    assert result["error"]["type"] == "ToolPreconditionError"
    assert inventory.get_item(item.id).quantity == 1
    assert _events(session) == before

    dispatcher.execute("search_items", {"query": "Renamed"})
    inventory.create_item("Other", aliases=["Renamed"])
    dispatcher.execute("search_locations", {"query": "Desk"})
    before = _events(session)
    result = dispatcher.execute(
        "move_item", {"item_id": item.id, "location_id": location.id}
    )
    assert result["error"]["type"] == "ToolPreconditionError"
    assert _events(session) == before


@pytest.mark.parametrize("entity", ["location", "category"])
def test_tree_path_change_rejects_stale_assignment(session: Session, entity: str) -> None:
    inventory = InventoryService(session)
    create = inventory.create_location if entity == "location" else inventory.create_category
    update = inventory.update_location if entity == "location" else inventory.update_category
    parent = create("Room")
    leaf = create("Shelf", parent_id=parent.id)
    item = inventory.create_item("Meter")
    dispatcher = ToolDispatcher(session)
    dispatcher.execute("search_items", {"query": "Meter"})
    dispatcher.execute("search_categories" if entity == "category" else "search_locations", {"query": "Room / Shelf"})
    update(parent.id, name="Other room")
    before = _events(session)
    if entity == "location":
        result = dispatcher.execute("move_item", {"item_id": item.id, "location_id": leaf.id})
        assert inventory.get_item(item.id).current_location_id is None
    else:
        result = dispatcher.execute("update_item", {"item_id": item.id, "category_id": leaf.id})
        assert inventory.get_item(item.id).category_id is None
    assert result["error"]["type"] == "ToolPreconditionError"
    assert _events(session) == before


def test_recheck_holds_sqlite_write_lock_through_mutation(tmp_path) -> None:
    database = tmp_path / "inventory.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    with factory() as session:
        inventory = InventoryService(session)
        item = inventory.create_item("Meter")
        dispatcher = ToolDispatcher(session, autocommit=False)
        dispatcher.execute("search_items", {"query": "Meter"})
        result = dispatcher.execute(
            "update_item", {"item_id": item.id, "description": "recounted"}
        )
        assert result["ok"] is True
        with sqlite3.connect(database, timeout=0.05) as other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE items SET quantity = 3 WHERE id = ?", (item.id,))
        session.commit()
        with sqlite3.connect(database, timeout=0.05) as other:
            other.execute("UPDATE items SET quantity = 3 WHERE id = ?", (item.id,))
        session.expire_all()
        assert inventory.get_item(item.id).quantity == 3
    engine.dispose()


def test_external_alias_collision_after_search_rejects_update(tmp_path) -> None:
    database = tmp_path / "inventory.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    with factory() as reader, factory() as writer:
        item = InventoryService(writer).create_item("Meter")
        dispatcher = ToolDispatcher(reader)
        assert dispatcher.execute("search_items", {"query": "Meter"})["ok"] is True
        InventoryService(writer).create_item("Other", aliases=["Meter"])
        before = _events(reader)
        result = dispatcher.execute(
            "update_item", {"item_id": item.id, "description": "recounted"}
        )
        assert result["error"]["type"] == "ToolPreconditionError"
        assert _events(reader) == before
        assert InventoryService(reader).get_item(item.id).quantity == 1
    engine.dispose()


@pytest.mark.parametrize("entity", ["location", "category"])
def test_stale_parent_reference_rejects_creation(session: Session, entity: str) -> None:
    inventory = InventoryService(session)
    create = inventory.create_location if entity == "location" else inventory.create_category
    update = inventory.update_location if entity == "location" else inventory.update_category
    parent = create("Room")
    dispatcher = ToolDispatcher(session)
    search = "search_locations" if entity == "location" else "search_categories"
    dispatcher.execute(search, {"query": "Room"})
    dispatcher.execute(search, {"query": "Shelf"})
    update(parent.id, name="Renamed")
    operation = "create_location" if entity == "location" else "create_category"
    result = dispatcher.execute(operation, {"name": "Shelf", "parent_id": parent.id})
    assert result["error"]["type"] == "ToolPreconditionError"
    assert all(node.name != "Shelf" for node in session.query(type(parent)))


def test_stale_existing_location_rejects_item_creation(session: Session) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Room")
    dispatcher = ToolDispatcher(session)
    dispatcher.execute("search_items", {"query": "New meter"})
    dispatcher.execute("search_locations", {"query": "Room"})
    inventory.update_location(location.id, name="Renamed")
    before = _events(session)
    result = dispatcher.execute("create_item", {"name": "New meter", "location_id": location.id})
    assert result["error"]["type"] == "ToolPreconditionError"
    assert session.scalar(select(func.count()).select_from(Base.metadata.tables["items"])) == 0
    assert _events(session) == before


def test_full_path_text_colliding_with_leaf_name_is_ambiguous(session: Session) -> None:
    inventory = InventoryService(session)
    room = inventory.create_location("Room")
    inventory.create_location("Shelf", parent_id=room.id)
    inventory.create_location("Room / Shelf")
    dispatcher = ToolDispatcher(session)

    found = dispatcher.execute("search_locations", {"query": "Room / Shelf"})
    assert found["ok"] is True
    assert not dispatcher.state.resolved["location"]
