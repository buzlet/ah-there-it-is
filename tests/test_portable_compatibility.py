from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import ChatRequestRecord, Conversation, Event
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage import (
    CURRENT_SCHEMA_REVISION,
    PORTABLE_EXPORT_VERSION,
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

    assert fixture.format == PORTABLE_EXPORT_VERSION
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
    finally:
        engine.dispose()

    reconstructed = export_portable_inventory(imported_url, reexported)
    assert _semantic_portable(reconstructed) == _semantic_portable(expected)
