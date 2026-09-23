from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient
from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.db.models import ChatRequestRecord
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.eval_fixture import seed_inventory_fixture
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage_ops import (
    PORTABLE_EXPORT_FORMAT,
    BackupValidationError,
    StorageOperationError,
    backup_database,
    expected_schema_revision,
    export_portable_json,
    restore_database,
    sqlite_database_path,
    validate_database_file,
)


def _migrated_database(tmp_path: Path, name: str = "active.db"):
    database = tmp_path / name
    url = f"sqlite:///{database}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_db_engine(url)
    factory = create_session_factory(engine)
    return database, url, engine, factory


def test_backup_uses_consistent_sqlite_snapshot_and_validates(tmp_path: Path) -> None:
    database, url, engine, factory = _migrated_database(tmp_path)
    backup = tmp_path / "backup.db"
    try:
        with factory() as session:
            ids = seed_inventory_fixture(session)
            gtx_id = ids.items["gtx1070"]

        # Keep the WAL-capable engine alive while taking the backup. The SQLite
        # backup API must still capture committed data without copying sidecars.
        validation = backup_database(url, backup)

        assert validation.path == str(backup.resolve())
        assert validation.schema_revision == expected_schema_revision()
        assert validation.integrity_ok is True
        assert validation.foreign_keys_ok is True
        assert backup.is_file()
        assert not Path(str(backup) + "-wal").exists()

        backup_engine = create_db_engine(f"sqlite:///{backup}")
        try:
            with Session(backup_engine) as session:
                assert SearchService(session).search_items("GTX 1070")[0].id == gtx_id
        finally:
            backup_engine.dispose()
    finally:
        engine.dispose()


def test_backup_refuses_to_overwrite_existing_archive(tmp_path: Path) -> None:
    _, url, engine, factory = _migrated_database(tmp_path)
    backup = tmp_path / "backup.db"
    try:
        with factory() as session:
            seed_inventory_fixture(session)
        backup_database(url, backup)
        original = backup.read_bytes()

        with pytest.raises(StorageOperationError, match="already exists"):
            backup_database(url, backup)

        assert backup.read_bytes() == original
        overwritten = backup_database(url, backup, overwrite=True)
        assert overwritten.path == str(backup.resolve())
    finally:
        engine.dispose()


def test_restore_is_validated_atomic_and_keeps_pre_restore_backup(
    tmp_path: Path,
) -> None:
    database, url, engine, factory = _migrated_database(tmp_path)
    candidate = tmp_path / "known-good.db"
    rollback = tmp_path / "before-restore.db"
    try:
        with factory() as session:
            ids = seed_inventory_fixture(session)
            item_id = ids.items["gtx1070"]
            old_location_id = ids.locations["old_hw"]
            new_location_id = ids.locations["desk_middle"]

        backup_database(url, candidate)

        with factory() as session:
            inventory = InventoryService(session)
            inventory.move_item(
                item_id,
                new_location_id,
                original_text="mutation after backup",
            )
            assert inventory.get_item(item_id).current_location_id == new_location_id
    finally:
        # Restore is deliberately an offline operation.
        engine.dispose()

    result = restore_database(
        url,
        candidate,
        confirm_app_stopped=True,
        rollback_backup=rollback,
    )
    assert result.restored_path == str(database.resolve())
    assert result.rollback_backup_path == str(rollback.resolve())
    assert validate_database_file(database).schema_revision == expected_schema_revision()
    assert validate_database_file(rollback).schema_revision == expected_schema_revision()

    restored_engine = create_db_engine(url)
    try:
        with Session(restored_engine) as session:
            inventory = InventoryService(session)
            assert inventory.get_item(item_id).current_location_id == old_location_id
            assert SearchService(session).search_items("Gigabyte GTX 1070")[0].id == item_id
            assert len(inventory.get_item_history(item_id)) == 1
    finally:
        restored_engine.dispose()

    rollback_engine = create_db_engine(f"sqlite:///{rollback}")
    try:
        with Session(rollback_engine) as session:
            inventory = InventoryService(session)
            assert inventory.get_item(item_id).current_location_id == new_location_id
            assert len(inventory.get_item_history(item_id)) == 2
    finally:
        rollback_engine.dispose()


def test_restore_refuses_rollback_path_that_is_candidate(tmp_path: Path) -> None:
    _, url, engine, factory = _migrated_database(tmp_path)
    candidate = tmp_path / "candidate.db"
    try:
        with factory() as session:
            seed_inventory_fixture(session)
        backup_database(url, candidate)
    finally:
        engine.dispose()

    with pytest.raises(StorageOperationError, match="differ from the restore candidate"):
        restore_database(
            url,
            candidate,
            confirm_app_stopped=True,
            rollback_backup=candidate,
        )


def test_restore_refuses_invalid_candidate_without_touching_active_database(
    tmp_path: Path,
) -> None:
    database, url, engine, factory = _migrated_database(tmp_path)
    bad = tmp_path / "broken.db"
    bad.write_bytes(b"not a sqlite database")
    try:
        with factory() as session:
            ids = seed_inventory_fixture(session)
            item_id = ids.items["gtx1070"]
    finally:
        engine.dispose()

    before = database.read_bytes()
    with pytest.raises(BackupValidationError):
        restore_database(
            url,
            bad,
            confirm_app_stopped=True,
        )
    assert database.read_bytes() == before

    with pytest.raises(StorageOperationError, match="confirmation"):
        restore_database(
            url,
            database.with_name("does-not-matter.db"),
            confirm_app_stopped=False,
        )


def test_emergency_restore_can_replace_corrupt_active_database(
    tmp_path: Path,
) -> None:
    database, url, engine, factory = _migrated_database(tmp_path)
    candidate = tmp_path / "known-good-emergency.db"
    try:
        with factory() as session:
            ids = seed_inventory_fixture(session)
            item_id = ids.items["gtx1070"]
        backup_database(url, candidate)
    finally:
        engine.dispose()

    Path(str(database) + "-wal").unlink(missing_ok=True)
    Path(str(database) + "-shm").unlink(missing_ok=True)
    database.write_bytes(b"corrupt active database")

    with pytest.raises(BackupValidationError):
        restore_database(
            url,
            candidate,
            confirm_app_stopped=True,
        )

    result = restore_database(
        url,
        candidate,
        confirm_app_stopped=True,
        skip_rollback=True,
    )
    assert result.rollback_backup_path is None
    assert validate_database_file(database).integrity_ok is True

    restored_engine = create_db_engine(url)
    try:
        with Session(restored_engine) as session:
            assert SearchService(session).search_items("GTX 1070")[0].id == item_id
    finally:
        restored_engine.dispose()


def test_validation_rejects_database_on_old_schema_revision(tmp_path: Path) -> None:
    database = tmp_path / "old-schema.db"
    url = f"sqlite:///{database}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "f19b2c4d6e81")

    with pytest.raises(BackupValidationError, match="does not match expected head"):
        validate_database_file(database)


def test_portable_export_separates_inventory_audit_and_evaluation(
    tmp_path: Path,
) -> None:
    _, url, engine, factory = _migrated_database(tmp_path)
    try:
        with factory() as session:
            ids = seed_inventory_fixture(session)
            result = AgentRunner(
                session,
                ScriptedLLMClient([LLMResponse(content="Stored answer")]),
            ).run("Snapshot conversation")

            ChatRequestService(session).execute(
                request_key="portable-completed-0001",
                message="Snapshot conversation",
                conversation_id=None,
                operation=lambda: result,
            )

            source = ChatRequestRecord(
                request_key="portable-failed-0001",
                requested_conversation_id=None,
                message="Risky retry",
                status="failed",
                error="simulated failure",
            )
            session.add(source)
            session.commit()
            session.refresh(source)
            session.add(
                ChatRequestRecord(
                    request_key="portable-recovery-0001",
                    requested_conversation_id=None,
                    message="Risky retry",
                    status="processing",
                    recovered_from_id=source.id,
                    recovery_note="operator inspected prior failure",
                )
            )
            session.commit()

        document = export_portable_json(url)
        assert document["format"] == PORTABLE_EXPORT_FORMAT
        assert document["schema_revision"] == expected_schema_revision()
        assert document["evaluation_included"] is False
        assert "evaluation" not in document

        items = document["inventory"]["items"]
        gtx = next(row for row in items if row["id"] == ids.items["gtx1070"])
        assert gtx["attributes"]["model"] == "GTX 1070"
        assert document["inventory"]["events"]
        assert isinstance(document["inventory"]["events"][0]["payload"], dict)

        requests = document["interaction_audit"]["chat_requests"]
        recovery = next(
            row
            for row in requests
            if row["request_key"] == "portable-recovery-0001"
        )
        assert recovery["recovered_from_id"] == source.id
        assert recovery["recovery_note"] == "operator inspected prior failure"
        assert document["interaction_audit"]["conversations"]
        assert document["interaction_audit"]["messages"]

        full = export_portable_json(url, include_evaluations=True)
        assert full["evaluation_included"] is True
        assert full["evaluation"]["agent_run_logs"]
        assert full["evaluation"]["agent_run_logs"][0]["final_content"] == "Stored answer"
        assert isinstance(full["evaluation"]["agent_run_logs"][0]["tool_trace"], list)
    finally:
        engine.dispose()


def test_sqlite_database_path_rejects_memory_and_non_sqlite() -> None:
    with pytest.raises(StorageOperationError, match="file-backed"):
        sqlite_database_path("sqlite://")
    with pytest.raises(StorageOperationError, match="SQLite only"):
        sqlite_database_path("postgresql://localhost/example")
