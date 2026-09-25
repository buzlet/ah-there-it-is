from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import Item
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.portable_stream import read_portable_workspace
from ah_there_it_is.storage import (
    PORTABLE_EXPORT_VERSION,
    PortableInventoryValidationError,
    export_portable_inventory,
    import_portable_inventory,
    parse_portable_inventory,
    validate_portable_workspace,
)


def _database(path: Path) -> str:
    url = f"sqlite:///{path}"
    upgrade_database(url)
    return url


def _semantic(document: dict) -> dict:
    result = deepcopy(document)
    result.pop("exported_at", None)
    result["source"].pop("alembic_revision", None)
    return result


def test_portable_v3_quantity_removed_roundtrip(tmp_path: Path) -> None:
    source_url = _database(tmp_path / "source.db")
    engine = create_db_engine(source_url)
    try:
        with Session(engine) as session:
            inventory = InventoryService(session)
            inventory.create_item(
                "Approx bolts", quantity_mode="approximate", quantity=20
            )
            inventory.create_item(
                "Unknown washers", quantity_mode="unknown", quantity=None
            )
            removed = inventory.create_item("Removed cable", quantity=2)
            inventory.remove_item(
                removed.id, reason="recycled", reason_source="explicit"
            )
    finally:
        engine.dispose()

    exported_path = tmp_path / "portable-v3.json"
    exported = export_portable_inventory(source_url, exported_path)
    assert exported["format"] == PORTABLE_EXPORT_VERSION
    assert [
        (item["quantity_mode"], item["quantity"], item["state"], item["removal_reason"])
        for item in exported["inventory"]["items"]
    ] == [
        ("approximate", 20, "unknown", None),
        ("unknown", None, "unknown", None),
        ("exact", 2, "removed", "recycled"),
    ]
    with read_portable_workspace(exported_path) as workspace:
        assert validate_portable_workspace(workspace).format == PORTABLE_EXPORT_VERSION

    active_url = _database(tmp_path / "active.db")
    imported_path = tmp_path / "imported.db"
    import_portable_inventory(active_url, exported_path, imported_path)
    reexported = export_portable_inventory(
        f"sqlite:///{imported_path}", tmp_path / "reexported.json"
    )
    assert _semantic(reexported) == _semantic(exported)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"quantity_mode": "unknown", "quantity": 2}, "quantity_mode"),
        ({"quantity_mode": "exact", "quantity": None}, "quantity_mode"),
        ({"state": "removed", "removal_reason": None, "location_status": "not_applicable"}, "removal_reason"),
        ({"state": "removed", "removal_reason": "gone", "location_status": "known"}, "contradictory"),
    ],
)
def test_portable_v3_rejects_contradictory_quantity_and_removed_truth(
    tmp_path: Path, changes: dict[str, object], message: str,
) -> None:
    url = _database(tmp_path / "source.db")
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            InventoryService(session).create_item("Meter")
    finally:
        engine.dispose()
    document = export_portable_inventory(url, tmp_path / "valid.json")
    document["inventory"]["items"][0].update(changes)
    with pytest.raises(PortableInventoryValidationError, match=message):
        parse_portable_inventory(document)


def test_portable_v2_legacy_terminal_states_import_as_removed(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "inventory-portable-v1.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["format"] = "inventory-portable-v2"
    states = ("sold", "discarded")
    for item, state in zip(document["inventory"]["items"], states, strict=False):
        item.update(
            state=state,
            location_id=None,
            location_status="not_applicable",
        )
    for item in document["inventory"]["items"][2:]:
        item["location_status"] = "known"
    source = tmp_path / "legacy-v2.json"
    source.write_text(json.dumps(document), encoding="utf-8")
    active_url = _database(tmp_path / "active.db")
    imported = tmp_path / "imported.db"
    import_portable_inventory(active_url, source, imported)
    engine = create_db_engine(f"sqlite:///{imported}")
    try:
        with Session(engine) as session:
            items = list(session.scalars(select(Item).order_by(Item.id)))
            assert [item.state for item in items[:2]] == ["removed", "removed"]
            assert [item.removal_reason for item in items[:2]] == list(states)
            assert [item.quantity_mode for item in items] == ["exact"] * 3
    finally:
        engine.dispose()
