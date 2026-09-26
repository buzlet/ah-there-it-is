"""Deterministic target-scale inventory fixture for structural read-path tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService


@dataclass(frozen=True)
class ScaleInventory:
    exact_name_id: int
    alias_id: int
    attribute_id: int
    tag_id: int
    description_id: int
    suggestion_target_id: int
    suggestion_related_id: int
    suggestion_location_id: int
    duplicate_location_ids: tuple[int, int]


def build_target_scale_inventory(session: Session) -> ScaleInventory:
    inventory = InventoryService(session, autocommit=False)

    location_ids: list[int] = []
    duplicate_ids: list[int] = []
    for root_index in range(10):
        root = inventory.create_location(f"Zone {root_index:02d}")
        location_ids.append(root.id)
        for leaf_index in range(19):
            leaf = inventory.create_location(
                f"Shelf {leaf_index:02d}",
                parent_id=root.id,
                description=f"Deterministic shelf {leaf_index:02d}",
            )
            location_ids.append(leaf.id)
            if leaf_index == 7 and root_index in (0, 1):
                duplicate_ids.append(leaf.id)
    assert len(location_ids) == 200

    category_ids: list[int] = []
    for root_index in range(5):
        root = inventory.create_category(f"Category {root_index:02d}")
        category_ids.append(root.id)
        for leaf_index in range(5):
            leaf = inventory.create_category(
                f"Group {root_index:02d}-{leaf_index:02d}",
                parent_id=root.id,
            )
            category_ids.append(leaf.id)

    suggestion_category = inventory.create_category("Suggestion Targets")

    special_names = {
        0: "Scale Exact Name Target",
        1: "Scale Alias Holder",
        2: "Scale Attribute Holder",
        3: "Scale Tag Holder",
        4: "Scale Description Holder",
        5: "Scale Suggestion Target",
        6: "Scale Suggestion Related",
    }
    ids: dict[int, int] = {}
    for index in range(1000):
        name = special_names.get(index, f"Inventory Item {index:04d}")
        aliases = [f"alias-{index:04d}"]
        tags = [f"bucket-{index % 17:02d}"]
        attributes = {
            "serial": f"SER-{index:04d}",
            "group": index % 11,
        }
        description = f"Deterministic inventory description {index:04d}."
        category_id = category_ids[index % len(category_ids)]
        location_id = location_ids[index % len(location_ids)]

        if index == 1:
            aliases.append("Scale Exact Alias")
        if index == 2:
            attributes["model"] = "SCALE-ATTRIBUTE-777"
        if index == 3:
            tags.append("scale-exact-tag")
        if index == 4:
            description = "Unique phosphor telescope description marker."
        if index == 5:
            category_id = suggestion_category.id
            location_id = None
            tags.append("scale-suggestion-shared")
        if index == 6:
            category_id = suggestion_category.id
            location_id = location_ids[42]
            tags.append("scale-suggestion-shared")
        if index in (997, 998, 999):
            location_id = None

        item = inventory.create_item(
            name,
            description=description,
            category_id=category_id,
            location_id=location_id,
            attributes=attributes,
            aliases=aliases,
            tags=tags,
        )
        if index <= 6:
            ids[index] = item.id

    session.commit()
    suggestion_location = location_ids[42]
    session.expunge_all()
    return ScaleInventory(
        exact_name_id=ids[0],
        alias_id=ids[1],
        attribute_id=ids[2],
        tag_id=ids[3],
        description_id=ids[4],
        suggestion_target_id=ids[5],
        suggestion_related_id=ids[6],
        suggestion_location_id=suggestion_location,
        duplicate_location_ids=(duplicate_ids[0], duplicate_ids[1]),
    )


def build_target_scale_database(path: Path) -> ScaleInventory:
    """Build the expensive immutable target-scale database once."""
    url = f"sqlite:///{path}"
    upgrade_database(url)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            return build_target_scale_inventory(session)
    finally:
        engine.dispose()


def clone_target_scale_database(source: Path, destination: Path) -> None:
    """Clone the template through SQLite backup so WAL state is included."""
    with sqlite3.connect(source) as original, sqlite3.connect(destination) as clone:
        original.backup(clone)
