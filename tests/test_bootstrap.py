from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.bootstrap import (
    BOOTSTRAP_FORMAT_VERSION,
    BOOTSTRAP_PROVENANCE,
    BootstrapPreflightError,
    BootstrapValidationError,
    apply_bootstrap_import,
    parse_bootstrap_manifest,
    preflight_bootstrap_import,
    validate_bootstrap_manifest,
)
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import (
    AgentFeedback,
    AgentRunLog,
    Alias,
    Category,
    ChatRequestRecord,
    Conversation,
    Event,
    ExperimentReview,
    ExperimentRun,
    Item,
    ItemTag,
    Location,
    Message,
    Tag,
)
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage import (
    CURRENT_SCHEMA_REVISION,
    export_portable_inventory,
    load_portable_inventory,
    validate_database,
)


FIXTURE = Path(__file__).parent / "fixtures" / "inventory-bootstrap-v1.json"


def _migrate(database: Path) -> str:
    url = f"sqlite:///{database}"
    upgrade_database(url)
    return url


def _fixture_document() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_hand_authored_fixture_is_valid() -> None:
    manifest = validate_bootstrap_manifest(FIXTURE)

    assert manifest.format == BOOTSTRAP_FORMAT_VERSION
    assert len(manifest.locations) == 5
    assert len(manifest.categories) == 4
    assert len(manifest.items) == 3


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda raw: raw.update(format="inventory-bootstrap-v2"), "unsupported bootstrap format"),
        (lambda raw: raw.update(unexpected=True), "(?i)extra inputs are not permitted"),
        (
            lambda raw: raw["locations"][0].update(path=["Office", " "]),
            "must not be blank",
        ),
        (
            lambda raw: raw["locations"].append(
                {"path": [" office "], "description": None}
            ),
            "duplicate normalized location path",
        ),
        (
            lambda raw: raw["locations"].append(
                {"path": ["Missing", "Child"], "description": None}
            ),
            "missing its immediate parent",
        ),
        (
            lambda raw: raw["items"][0].update(location_path=["Nowhere"]),
            "does not reference a manifest location",
        ),
        (
            lambda raw: raw["items"][0].update(category_path=["Nowhere"]),
            "does not reference a manifest category",
        ),
        (
            lambda raw: raw["items"].append(
                {
                    **deepcopy(raw["items"][0]),
                    "name": " orico usb-sata adapter ",
                }
            ),
            "duplicate item identity",
        ),
        (
            lambda raw: raw["items"][0].update(state="excellent"),
            "not a valid ItemState",
        ),
        (
            lambda raw: raw["items"][0].update(quantity=0),
            "greater than or equal to 1",
        ),
        (
            lambda raw: raw["items"][0].update(aliases=["USB bridge", " usb bridge "]),
            "duplicate normalized value",
        ),
        (
            lambda raw: raw["items"][0].update(aliases=[" "]),
            "must not be blank",
        ),
        (
            lambda raw: raw["items"][0].update(tags=["USB", " usb "]),
            "duplicate normalized value",
        ),
        (
            lambda raw: raw["items"][0].update(tags=[""]),
            "must not be blank",
        ),
        (
            lambda raw: raw["items"][0].update(attributes=[]),
            "valid dictionary",
        ),
    ],
)
def test_parser_rejects_invalid_bootstrap_semantics(mutate, match: str) -> None:
    raw = _fixture_document()
    mutate(raw)

    with pytest.raises(BootstrapValidationError, match=match):
        parse_bootstrap_manifest(raw)


def test_parser_rejects_duplicate_category_path_and_blank_item_name() -> None:
    duplicate = _fixture_document()
    duplicate["categories"].append(
        {"path": [" electronics "], "description": None}
    )
    with pytest.raises(BootstrapValidationError, match="duplicate normalized category path"):
        parse_bootstrap_manifest(duplicate)

    blank = _fixture_document()
    blank["items"][0]["name"] = " "
    with pytest.raises(BootstrapValidationError, match="name must not be blank"):
        parse_bootstrap_manifest(blank)


def test_preflight_rejects_non_current_schema_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    url = _migrate(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE alembic_version SET version_num = ?",
            ("c4cfe3a3e921",),
        )
        connection.commit()
    finally:
        connection.close()
    before = database.read_bytes()

    with pytest.raises(BootstrapPreflightError, match="does not match expected"):
        preflight_bootstrap_import(url, FIXTURE)

    assert database.read_bytes() == before


def test_preflight_rejects_nonempty_inventory_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "nonempty.db"
    url = _migrate(database)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            InventoryService(session).create_location("Existing")
    finally:
        engine.dispose()
    before = validate_database(database).sha256

    with pytest.raises(BootstrapPreflightError, match="empty inventory domain"):
        preflight_bootstrap_import(url, FIXTURE)

    assert validate_database(database).sha256 == before


def test_preflight_ignores_operational_rows_and_does_not_mutate(tmp_path: Path) -> None:
    database = tmp_path / "operational.db"
    url = _migrate(database)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            session.add(Conversation())
            session.commit()
    finally:
        engine.dispose()
    before = validate_database(database).sha256

    result = preflight_bootstrap_import(url, FIXTURE)

    assert result.alembic_revision == CURRENT_SCHEMA_REVISION
    assert result.items == 3
    assert validate_database(database).sha256 == before


def test_apply_preserves_existing_operational_state(tmp_path: Path) -> None:
    database = tmp_path / "operational-apply.db"
    url = _migrate(database)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            conversation = Conversation()
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id
    finally:
        engine.dispose()

    apply_bootstrap_import(url, FIXTURE)

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            conversations = list(session.scalars(select(Conversation)))
            assert [row.id for row in conversations] == [conversation_id]
            assert session.scalar(select(func.count(Item.id))) == 3
    finally:
        engine.dispose()


def test_successful_bootstrap_uses_domain_services_search_and_portable_export(
    tmp_path: Path,
) -> None:
    database = tmp_path / "bootstrap.db"
    exported = tmp_path / "portable.json"
    url = _migrate(database)

    result = apply_bootstrap_import(url, FIXTURE)

    assert result.format == BOOTSTRAP_FORMAT_VERSION
    assert (result.categories, result.locations, result.items, result.events) == (4, 5, 3, 3)

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            adapter = search.search_items("ORICO USB-SATA adapter")[0]
            assert search.search_items("USB-SATA bridge")[0].id == adapter.id
            assert search.search_items("SATA")[0].id == adapter.id
            assert search.search_items("USB 3.0 to SATA")[0].id == adapter.id
            assert search.search_items("firmware recovery")[0].id == adapter.id
            assert adapter.location_path == "Office / Desk / Right drawer"
            assert adapter.category_path == "Electronics / Adapters"

            assert search.search_locations("Office Desk Right drawer")[0].path == (
                "Office / Desk / Right drawer"
            )
            assert search.search_categories("Electronics Adapters")[0].path == (
                "Electronics / Adapters"
            )

            items = list(session.scalars(select(Item).order_by(Item.id)))
            events = list(session.scalars(select(Event).order_by(Event.id)))
            assert len(items) == 3
            assert len(events) == len(items)
            assert all(event.event_type == "item_created" for event in events)
            assert all(event.original_text == BOOTSTRAP_PROVENANCE for event in events)
            assert [event.item_id for event in events] == [item.id for item in items]
            assert all(event.from_location_id is None for event in events)
            by_item = {item.id: item for item in items}
            assert all(
                event.to_location_id == by_item[event.item_id].current_location_id
                and event.payload == {
                    "name": by_item[event.item_id].name,
                    "quantity": by_item[event.item_id].quantity,
                }
                for event in events
            )

            operational_models = (
                Conversation,
                Message,
                AgentRunLog,
                ChatRequestRecord,
                AgentFeedback,
                ExperimentRun,
                ExperimentReview,
            )
            assert all(
                int(session.scalar(select(func.count()).select_from(model)) or 0) == 0
                for model in operational_models
            )
    finally:
        engine.dispose()

    portable = export_portable_inventory(url, exported)
    assert portable["format"] == "inventory-portable-v1"
    loaded = load_portable_inventory(exported)
    assert len(loaded.inventory.items) == 3
    assert len(loaded.history.events) == 3


def test_bootstrap_apply_rolls_back_complete_transaction_on_mid_apply_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database = tmp_path / "rollback.db"
    url = _migrate(database)
    original = InventoryService.create_item
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated mid-apply failure")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(InventoryService, "create_item", fail_second)

    with pytest.raises(RuntimeError, match="simulated mid-apply failure"):
        apply_bootstrap_import(url, FIXTURE)

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            domain_models = (Category, Location, Item, Alias, Tag, ItemTag, Event)
            assert all(
                int(session.scalar(select(func.count()).select_from(model)) or 0) == 0
                for model in domain_models
            )
    finally:
        engine.dispose()


def test_bootstrap_cli_preflight_and_apply_are_machine_readable_and_dry(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from ah_there_it_is.config import get_settings
    from ah_there_it_is.storage_cli import main as storage_cli_main

    database = tmp_path / "cli.db"
    url = _migrate(database)
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        before = validate_database(database).sha256
        monkeypatch.setattr(
            "sys.argv",
            ["storage_cli", "bootstrap-preflight", str(FIXTURE)],
        )
        storage_cli_main()
        preflight = json.loads(capsys.readouterr().out)
        assert preflight["format"] == BOOTSTRAP_FORMAT_VERSION
        assert preflight["items"] == 3
        assert validate_database(database).sha256 == before

        engine = create_db_engine(url)
        try:
            with Session(engine) as session:
                assert session.scalar(select(func.count(Item.id))) == 0
                assert session.scalar(select(func.count(Event.id))) == 0
        finally:
            engine.dispose()

        monkeypatch.setattr(
            "sys.argv",
            ["storage_cli", "bootstrap-apply", str(FIXTURE)],
        )
        storage_cli_main()
        applied = json.loads(capsys.readouterr().out)
        assert applied["format"] == BOOTSTRAP_FORMAT_VERSION
        assert applied["items"] == 3
        assert applied["events"] == 3
    finally:
        get_settings.cache_clear()
