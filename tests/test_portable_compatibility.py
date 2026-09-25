from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import ChatRequestRecord, Conversation, Event, Item
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage import (
    CURRENT_SCHEMA_REVISION,
    PORTABLE_EXPORT_VERSION,
    PORTABLE_V2_VERSION,
    PORTABLE_V1_VERSION,
    PortableItem,
    PortableInventoryValidationError,
    parse_portable_inventory,
    export_portable_inventory,
    import_portable_inventory,
    load_portable_inventory,
    validate_database,
)


FIXTURE = Path(__file__).parent / "fixtures" / "inventory-portable-v1.json"
FIXTURE_SOURCE_REVISION = "c4cfe3a3e921"


def _migrate(database: Path) -> str:
    url = f"sqlite:///{database}"
    upgrade_database(url)
    return url


def _semantic_portable(document: dict) -> dict:
    normalized = deepcopy(document)
    normalized.pop("exported_at", None)
    normalized["source"].pop("alembic_revision", None)
    for item in normalized["inventory"]["items"]:
        item["aliases"] = sorted(item["aliases"], key=str.casefold)
        item["tags"] = sorted(item["tags"], key=str.casefold)
    return normalized


def test_inventory_portable_v1_fixture_contract(tmp_path: Path, monkeypatch) -> None:
    fixture = load_portable_inventory(FIXTURE)
    expected = fixture.model_dump(mode="json")

    assert fixture.format == PORTABLE_V1_VERSION
    assert fixture.source.alembic_revision == FIXTURE_SOURCE_REVISION
    assert set(expected) == {
        "format",
        "exported_at",
        "source",
        "inventory",
        "history",
        "excluded",
    }

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    active = tmp_path / "active.db"
    imported = tmp_path / "imported.db"
    reexported = tmp_path / "reexported.json"
    active_url = _migrate(active)

    result = import_portable_inventory(active_url, FIXTURE, imported)

    assert result.source_alembic_revision == FIXTURE_SOURCE_REVISION
    assert result.items == 3
    assert result.events == 3
    assert validate_database(imported).alembic_revision == CURRENT_SCHEMA_REVISION

    imported_url = f"sqlite:///{imported}"
    engine = create_db_engine(imported_url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            assert search.search_items("USB Programmer")[0].id == 1001
            assert search.search_items("CH341A")[0].id == 1001
            assert search.search_items("BIOS")[0].id == 1001
            assert search.search_items("firmware recovery")[0].id == 1001

            assert list(session.scalars(select(Event.id).order_by(Event.id))) == [
                5001,
                5002,
                5003,
            ]
            assert session.scalar(select(func.count(Conversation.id))) == 0
            assert session.scalar(select(func.count(ChatRequestRecord.id))) == 0
            imported_items = list(session.scalars(select(Item).order_by(Item.id)))
            assert [item.location_status for item in imported_items] == ["known"] * 3
    finally:
        engine.dispose()

    reconstructed = export_portable_inventory(imported_url, reexported)
    expected_v3 = deepcopy(expected)
    expected_v3["format"] = PORTABLE_EXPORT_VERSION
    for item in expected_v3["inventory"]["items"]:
        item["location_status"] = (
            "known" if item["location_id"] is not None
            else "not_applicable" if item["state"] == "discarded"
            else "unknown"
        )
        item["quantity_mode"] = "exact"
        item["removal_reason"] = None
    assert _semantic_portable(reconstructed) == _semantic_portable(expected_v3)



def test_portable_v1_contract_stays_frozen_and_v2_adds_location_truth() -> None:
    raw_v1 = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "location_status" not in PortableItem.model_fields
    assert all("location_status" not in item for item in raw_v1["inventory"]["items"])
    parsed_v1 = parse_portable_inventory(raw_v1)
    assert parsed_v1.format == PORTABLE_V1_VERSION

    with_new_field = deepcopy(raw_v1)
    with_new_field["inventory"]["items"][0]["location_status"] = "known"
    with pytest.raises(PortableInventoryValidationError, match="Extra inputs"):
        parse_portable_inventory(with_new_field)

    raw_v2 = deepcopy(raw_v1)
    raw_v2["format"] = PORTABLE_V2_VERSION
    for item in raw_v2["inventory"]["items"]:
        item["location_status"] = (
            "known" if item["location_id"] is not None
            else "not_applicable" if item["state"] == "discarded"
            else "unknown"
        )
    sold_item = deepcopy(raw_v2["inventory"]["items"][0])
    sold_item.update(
        id=1004, name="Sold item", state="sold", category_id=None,
        location_id=None, location_status="not_applicable", aliases=[], tags=[],
    )
    raw_v2["inventory"]["items"].append(sold_item)
    parsed_v2 = parse_portable_inventory(raw_v2)
    assert parsed_v2.format == PORTABLE_V2_VERSION
    assert parsed_v2.inventory.items[0].location_status == "known"
    assert parsed_v2.inventory.items[-1].state == "sold"

    contradictory = deepcopy(raw_v2)
    contradictory["inventory"]["items"][0]["location_status"] = "unknown"
    with pytest.raises(PortableInventoryValidationError, match="contradictory"):
        parse_portable_inventory(contradictory)

    sold_in_v1 = deepcopy(raw_v1)
    sold_in_v1["inventory"]["items"][0].update(
        state="sold", location_id=None
    )
    assert parse_portable_inventory(sold_in_v1).inventory.items[0].state == "sold"
