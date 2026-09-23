from __future__ import annotations

import json
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
    PORTABLE_EXPORT_VERSION,
    DatabaseValidationError,
    StorageError,
    create_backup,
    expected_alembic_head,
    export_portable_inventory,
    restore_backup,
    validate_database,
)


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
    assert restored.restored.sha256 == restored.candidate.sha256

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
