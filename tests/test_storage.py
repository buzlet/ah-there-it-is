from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import (
    ChatRequestRecord,
    Conversation,
    Event,
    Message,
)
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.eval_fixture import seed_inventory_fixture
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage import (
    CURRENT_SCHEMA_REVISION,
    PORTABLE_EXPORT_VERSION,
    DatabaseValidationError,
    PortableInventoryValidationError,
    StorageError,
    create_backup,
    expected_alembic_head,
    export_portable_inventory,
    import_portable_inventory,
    parse_portable_inventory,
    validate_portable_import_target,
    restore_backup,
    validate_database,
)
from ah_there_it_is.storage_cli import main as storage_cli_main


def _migrate(database: Path) -> str:
    url = f"sqlite:///{database}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


def _seed_operational_state(database_url: str) -> dict[str, int]:
    engine = create_db_engine(database_url)
    try:
        with Session(engine) as session:
            ids = seed_inventory_fixture(session)
            conversation = Conversation()
            session.add(conversation)
            session.flush()
            session.add_all(
                [
                    Message(
                        conversation_id=conversation.id,
                        role="user",
                        content="Где CH341A?",
                    ),
                    Message(
                        conversation_id=conversation.id,
                        role="assistant",
                        content="В правом ящике.",
                    ),
                ]
            )
            failed = ChatRequestRecord(
                request_key="failed-original",
                requested_conversation_id=conversation.id,
                message="Переложи CH341A",
                status="failed",
                error="simulated crash",
            )
            session.add(failed)
            session.flush()
            recovery = ChatRequestRecord(
                request_key="recovery-attempt",
                requested_conversation_id=conversation.id,
                message=failed.message,
                status="processing",
                recovered_from_id=failed.id,
                recovery_note="operator accepted duplicate risk",
            )
            session.add(recovery)
            session.commit()
            return {
                "ch341a": ids.items["ch341a"],
                "middle": ids.locations["desk_middle"],
                "conversation": conversation.id,
                "failed_request": failed.id,
                "recovery_request": recovery.id,
            }
    finally:
        engine.dispose()


def test_runtime_schema_revision_matches_migration_head() -> None:
    assert CURRENT_SCHEMA_REVISION == expected_alembic_head()


def test_backup_restore_round_trip_preserves_application_state(tmp_path: Path) -> None:
    active = tmp_path / "active.db"
    backup = tmp_path / "backup.db"
    url = _migrate(active)
    ids = _seed_operational_state(url)

    before = validate_database(active)
    created = create_backup(url, backup)

    assert created.path == str(backup.resolve())
    assert created.alembic_revision == expected_alembic_head()
    assert created.integrity_check == ("ok",)
    assert created.foreign_key_violations == ()
    assert created.sha256
    assert before.alembic_revision == created.alembic_revision

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            inventory = InventoryService(session)
            inventory.move_item(
                ids["ch341a"],
                ids["middle"],
                original_text="post-backup mutation",
            )
            session.add(
                Message(
                    conversation_id=ids["conversation"],
                    role="user",
                    content="Это сообщение появилось после backup.",
                )
            )
            session.commit()
    finally:
        engine.dispose()

    restored = restore_backup(url, backup)

    assert Path(restored.safety_backup_path).is_file()
    assert restored.restored.alembic_revision == expected_alembic_head()
    assert restored.restored.integrity_check == ("ok",)
    assert restored.restored.foreign_key_violations == ()
    # SQLite's backup API guarantees a consistent logical snapshot, not
    # byte-for-byte page layout identity. Physical SHA-256 values may differ
    # after writing the validated candidate into the active database.
    assert restored.restored.sha256
    assert restored.candidate.sha256

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            ch341a = search.search_items("SPI flash")[0]
            assert ch341a.id == ids["ch341a"]
            assert ch341a.location_path.endswith("Стол / Правый ящик")
            assert search.search_items("программатор BIOS")[0].id == ids["ch341a"]

            messages = list(
                session.scalars(
                    select(Message)
                    .where(Message.conversation_id == ids["conversation"])
                    .order_by(Message.id)
                )
            )
            assert [message.content for message in messages] == [
                "Где CH341A?",
                "В правом ящике.",
            ]

            requests = list(
                session.scalars(
                    select(ChatRequestRecord).order_by(ChatRequestRecord.id)
                )
            )
            assert len(requests) == 2
            assert requests[0].id == ids["failed_request"]
            assert requests[0].status == "failed"
            assert requests[1].id == ids["recovery_request"]
            assert requests[1].recovered_from_id == requests[0].id
            assert requests[1].recovery_note == "operator accepted duplicate risk"

            event_count = int(
                session.scalar(select(func.count(Event.id))) or 0
            )
            assert event_count == 8
    finally:
        engine.dispose()


def test_backup_includes_committed_uncheckpointed_wal_data(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.db"
    backup = tmp_path / "wal-backup.db"
    url = _migrate(active)
    ids = _seed_operational_state(url)

    raw = __import__("sqlite3").connect(str(active))
    try:
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA wal_autocheckpoint=0")
        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) "
            "VALUES (?, 'user', ?, CURRENT_TIMESTAMP)",
            (ids["conversation"], "committed only in WAL"),
        )
        raw.commit()
        wal = Path(str(active) + "-wal")
        assert wal.is_file()
        assert wal.stat().st_size > 0

        create_backup(url, backup)
    finally:
        raw.close()

    validate_database(backup)
    backup_connection = __import__("sqlite3").connect(str(backup))
    try:
        count = backup_connection.execute(
            "SELECT count(*) FROM messages WHERE content = ?",
            ("committed only in WAL",),
        ).fetchone()[0]
    finally:
        backup_connection.close()

    assert count == 1


def test_invalid_restore_candidate_never_replaces_active_database(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.db"
    url = _migrate(active)
    ids = _seed_operational_state(url)
    before = validate_database(active)

    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not sqlite")

    with pytest.raises(DatabaseValidationError):
        restore_backup(url, corrupt)

    after = validate_database(active)
    assert after.sha256 == before.sha256

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            assert SearchService(session).search_items("CH341A")[0].id == ids["ch341a"]
    finally:
        engine.dispose()


def test_backup_refuses_overwrite_and_active_path(tmp_path: Path) -> None:
    active = tmp_path / "active.db"
    backup = tmp_path / "backup.db"
    url = _migrate(active)
    _seed_operational_state(url)

    create_backup(url, backup)
    with pytest.raises(StorageError, match="already exists"):
        create_backup(url, backup)
    with pytest.raises(StorageError, match="must differ"):
        create_backup(url, active)


def test_portable_export_contains_core_inventory_not_provider_traces(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.db"
    output = tmp_path / "inventory.json"
    url = _migrate(active)
    ids = _seed_operational_state(url)

    document = export_portable_inventory(url, output)
    loaded = json.loads(output.read_text(encoding="utf-8"))

    assert document == loaded
    assert loaded["format"] == PORTABLE_EXPORT_VERSION
    assert loaded["source"]["alembic_revision"] == expected_alembic_head()
    assert loaded["inventory"]["categories"]
    assert loaded["inventory"]["locations"]
    assert loaded["history"]["events"]

    ch341a = next(
        item for item in loaded["inventory"]["items"]
        if item["id"] == ids["ch341a"]
    )
    assert ch341a["attributes"]["model"] == "CH341A"
    assert "CH341A" in ch341a["aliases"]
    assert {"BIOS", "SPI", "flash"} <= set(ch341a["tags"])

    serialized = output.read_text(encoding="utf-8")
    assert "agent_run_logs" in loaded["excluded"]
    assert "experiment_runs" in loaded["excluded"]
    assert "llm_provider" not in serialized
    assert "tool_trace" not in serialized


def test_validation_rejects_wrong_alembic_revision(tmp_path: Path) -> None:
    active = tmp_path / "active.db"
    _migrate(active)

    with pytest.raises(DatabaseValidationError, match="does not match expected"):
        validate_database(active, expected_revision="not-the-current-head")


def _minimal_portable_document() -> dict:
    stamp = "2026-09-23T07:00:00+00:00"
    return {
        "format": PORTABLE_EXPORT_VERSION,
        "exported_at": stamp,
        "source": {"alembic_revision": CURRENT_SCHEMA_REVISION},
        "inventory": {
            "categories": [
                {
                    "id": 1,
                    "parent_id": None,
                    "name": "Electronics",
                    "description": None,
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            ],
            "locations": [
                {
                    "id": 2,
                    "parent_id": None,
                    "name": "Desk",
                    "description": None,
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            ],
            "items": [
                {
                    "id": 3,
                    "name": "Programmer",
                    "description": "USB programmer",
                    "state": "unknown",
                    "category_id": 1,
                    "location_id": 2,
                    "quantity": 1,
                    "attributes": {"model": "CH341A"},
                    "aliases": ["CH341A"],
                    "tags": ["SPI"],
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            ],
        },
        "history": {
            "events": [
                {
                    "id": 4,
                    "event_type": "item_created",
                    "item_id": 3,
                    "from_location_id": None,
                    "to_location_id": 2,
                    "payload": {"name": "Programmer", "quantity": 1},
                    "original_text": None,
                    "created_at": stamp,
                }
            ]
        },
        "excluded": [
            "agent_run_logs",
            "agent_feedback",
            "experiment_runs",
            "experiment_reviews",
            "provider_metadata",
        ],
    }


def test_portable_parser_accepts_valid_document() -> None:
    document = parse_portable_inventory(_minimal_portable_document())

    assert document.format == PORTABLE_EXPORT_VERSION
    assert document.inventory.items[0].id == 3
    assert document.history.events[0].to_location_id == 2


@pytest.mark.parametrize(
    "value",
    [None, "inventory-portable-v2", 12],
)
def test_portable_parser_rejects_unknown_or_invalid_format(value: object) -> None:
    raw = _minimal_portable_document()
    raw["format"] = value

    with pytest.raises(PortableInventoryValidationError, match="format"):
        parse_portable_inventory(raw)


def test_portable_parser_rejects_missing_format_and_bad_structure() -> None:
    missing = _minimal_portable_document()
    del missing["format"]
    with pytest.raises(PortableInventoryValidationError, match="missing required format"):
        parse_portable_inventory(missing)

    malformed = _minimal_portable_document()
    malformed["inventory"]["items"] = {}
    with pytest.raises(PortableInventoryValidationError, match="inventory.items"):
        parse_portable_inventory(malformed)

    derived = _minimal_portable_document()
    derived["inventory"]["items"][0]["normalized_name"] = "programmer"
    with pytest.raises(PortableInventoryValidationError, match="normalized_name"):
        parse_portable_inventory(derived)


def test_portable_parser_rejects_duplicate_ids_and_dangling_references() -> None:
    duplicate = _minimal_portable_document()
    duplicate["inventory"]["categories"].append(
        deepcopy(duplicate["inventory"]["categories"][0])
    )
    with pytest.raises(PortableInventoryValidationError, match="duplicate category id=1"):
        parse_portable_inventory(duplicate)

    dangling = _minimal_portable_document()
    dangling["inventory"]["items"][0]["location_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing location id=999"):
        parse_portable_inventory(dangling)

    event = _minimal_portable_document()
    event["history"]["events"][0]["item_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing item id=999"):
        parse_portable_inventory(event)


def test_portable_parser_rejects_invalid_hierarchies() -> None:
    self_parent = _minimal_portable_document()
    self_parent["inventory"]["categories"][0]["parent_id"] = 1
    with pytest.raises(PortableInventoryValidationError, match="own parent"):
        parse_portable_inventory(self_parent)

    cycle = _minimal_portable_document()
    first = cycle["inventory"]["locations"][0]
    first["parent_id"] = 5
    cycle["inventory"]["locations"].append(
        {
            **deepcopy(first),
            "id": 5,
            "parent_id": 2,
            "name": "Shelf",
        }
    )
    with pytest.raises(PortableInventoryValidationError, match="hierarchy cycle"):
        parse_portable_inventory(cycle)

    sibling = _minimal_portable_document()
    sibling["inventory"]["categories"].append(
        {
            **deepcopy(sibling["inventory"]["categories"][0]),
            "id": 6,
            "name": "  ELECTRONICS  ",
        }
    )
    with pytest.raises(PortableInventoryValidationError, match="duplicate sibling"):
        parse_portable_inventory(sibling)


def test_portable_parser_rejects_invalid_names_state_and_timestamps() -> None:
    aliases = _minimal_portable_document()
    aliases["inventory"]["items"][0]["aliases"] = ["CH341A", " ch341a "]
    with pytest.raises(PortableInventoryValidationError, match="aliases.*duplicate"):
        parse_portable_inventory(aliases)

    tags = _minimal_portable_document()
    second = deepcopy(tags["inventory"]["items"][0])
    second["id"] = 7
    second["name"] = "Other"
    second["aliases"] = []
    second["tags"] = [" spi "]
    tags["inventory"]["items"].append(second)
    with pytest.raises(PortableInventoryValidationError, match="conflicts with existing spelling"):
        parse_portable_inventory(tags)

    state = _minimal_portable_document()
    state["inventory"]["items"][0]["state"] = "teleported"
    with pytest.raises(PortableInventoryValidationError, match="invalid value"):
        parse_portable_inventory(state)

    timestamp = _minimal_portable_document()
    timestamp["inventory"]["items"][0]["created_at"] = "2026-09-23 07:00:00"
    with pytest.raises(PortableInventoryValidationError, match="timezone offset"):
        parse_portable_inventory(timestamp)


def _semantic_portable(document: dict) -> dict:
    normalized = deepcopy(document)
    normalized.pop("exported_at", None)
    for item in normalized["inventory"]["items"]:
        item["aliases"] = sorted(item["aliases"], key=str.casefold)
        item["tags"] = sorted(item["tags"], key=str.casefold)
    return normalized


def test_portable_import_round_trip_preserves_domain_and_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = tmp_path / "active.db"
    exported = tmp_path / "inventory.json"
    imported = tmp_path / "imported.db"
    reexported = tmp_path / "inventory-reexported.json"
    url = _migrate(active)
    ids = _seed_operational_state(url)
    original = export_portable_inventory(url, exported)
    before_active = validate_database(active)

    # An ambient active-DB override must not hijack Alembic during portable import.
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", url)
    result = import_portable_inventory(url, exported, imported)

    assert result.imported_path == str(imported.resolve())
    assert result.items == len(original["inventory"]["items"])
    assert validate_database(imported).alembic_revision == CURRENT_SCHEMA_REVISION
    assert validate_database(active).sha256 == before_active.sha256

    imported_url = f"sqlite:///{imported}"
    engine = create_db_engine(imported_url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            assert search.search_items("SPI flash")[0].id == ids["ch341a"]
            assert search.search_items("CH341A")[0].id == ids["ch341a"]
            assert search.search_items("BIOS")[0].id == ids["ch341a"]

            event_ids = list(session.scalars(select(Event.id).order_by(Event.id)))
            assert event_ids == [
                event["id"] for event in original["history"]["events"]
            ]
            assert session.scalar(select(func.count(Conversation.id))) == 0
            assert session.scalar(select(func.count(ChatRequestRecord.id))) == 0
    finally:
        engine.dispose()

    reconstructed = export_portable_inventory(imported_url, reexported)
    assert _semantic_portable(reconstructed) == _semantic_portable(original)


def test_portable_import_refuses_existing_active_and_invalid_targets(
    tmp_path: Path,
) -> None:
    active = tmp_path / "active.db"
    source = tmp_path / "inventory.json"
    url = _migrate(active)
    _seed_operational_state(url)
    export_portable_inventory(url, source)

    existing = tmp_path / "existing.db"
    existing.write_bytes(b"do not replace")
    with pytest.raises(StorageError, match="already exists"):
        import_portable_inventory(url, source, existing)
    assert existing.read_bytes() == b"do not replace"

    with pytest.raises(StorageError, match="active database"):
        validate_portable_import_target(url, active)

    invalid_source = tmp_path / "invalid.json"
    invalid = json.loads(source.read_text(encoding="utf-8"))
    invalid["inventory"]["items"][0]["location_id"] = 999999
    invalid_source.write_text(json.dumps(invalid), encoding="utf-8")
    absent = tmp_path / "must-not-exist.db"
    with pytest.raises(PortableInventoryValidationError, match="missing location"):
        import_portable_inventory(url, invalid_source, absent)
    assert not absent.exists()


def test_portable_import_dry_run_cli_creates_no_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "minimal.json"
    target = tmp_path / "dry-run.db"
    source.write_text(
        json.dumps(_minimal_portable_document(), ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "AH_THERE_IT_IS_DATABASE_URL",
        f"sqlite:///{tmp_path / 'active.db'}",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "storage_cli",
            "import-json",
            str(source),
            str(target),
            "--dry-run",
        ],
    )

    storage_cli_main()

    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["items"] == 1
    assert result["events"] == 1
    assert not target.exists()
    assert not Path(str(target) + "-wal").exists()
    assert not Path(str(target) + "-shm").exists()
