from __future__ import annotations

import json
import io
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import event as sqlalchemy_event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import (
    AgentRunLog,
    Alias,
    ChatRequestRecord,
    Conversation,
    Category,
    Event,
    Item,
    ItemTag,
    Location,
    Message,
    Tag,
    ExperimentRun,
)
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.eval_fixture import seed_inventory_fixture
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.database_doctor import diagnose_database
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
    _portable_document,
    _write_json_array,
    stream_portable_inventory,
)
from ah_there_it_is.storage_cli import main as storage_cli_main


def _migrate(database: Path) -> str:
    url = f"sqlite:///{database}"
    upgrade_database(url)
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


@pytest.mark.parametrize(
    "failure_stage",
    [
        "candidate_copy",
        "staging_validation",
        "checkpoint",
        "replace",
        "post_validation",
        "rollback_copy",
        "rollback_replace",
        "rollback_validation",
    ],
)
def test_restore_failure_and_rollback_outcomes_are_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    import ah_there_it_is.storage as storage

    active = tmp_path / f"restore-{failure_stage}.db"
    candidate = tmp_path / f"candidate-{failure_stage}.db"
    safety = tmp_path / f"safety-{failure_stage}.db"
    url = _migrate(active)
    _seed_operational_state(url)
    create_backup(url, candidate)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            InventoryService(session).create_item("Active newer item")
    finally:
        engine.dispose()

    original_copy = storage._copy_sqlite_snapshot
    original_validate = storage.validate_database
    original_replace = storage.os.replace
    replace_state = {"restore_published": False, "active_validations": 0}

    if failure_stage in {"candidate_copy", "rollback_copy"}:
        def injected_copy(source: Path, destination: Path) -> None:
            name = destination.name
            if failure_stage == "candidate_copy" and ".restore." in name:
                raise OSError("candidate copy fault")
            if failure_stage == "rollback_copy" and ".rollback." in name:
                raise OSError("rollback copy fault")
            original_copy(source, destination)

        monkeypatch.setattr(storage, "_copy_sqlite_snapshot", injected_copy)

    if failure_stage == "checkpoint":
        monkeypatch.setattr(
            storage,
            "_checkpoint_for_restore",
            lambda _target: (_ for _ in ()).throw(StorageError("checkpoint fault")),
        )

    if failure_stage in {"replace", "rollback_replace"}:
        def injected_replace(source: Path, target: Path) -> None:
            if failure_stage == "replace" and ".restore." in source.name:
                raise OSError("restore replace fault")
            if failure_stage == "rollback_replace" and ".rollback." in source.name:
                raise OSError("rollback replace fault")
            original_replace(source, target)
            if target == active and ".restore." in source.name:
                replace_state["restore_published"] = True

        monkeypatch.setattr(storage.os, "replace", injected_replace)
    else:
        def observed_replace(source: Path, target: Path) -> None:
            original_replace(source, target)
            if target == active and ".restore." in source.name:
                replace_state["restore_published"] = True

        monkeypatch.setattr(storage.os, "replace", observed_replace)

    if failure_stage in {
        "staging_validation", "post_validation", "rollback_copy",
        "rollback_replace", "rollback_validation",
    }:
        def injected_validate(path, **kwargs):
            candidate_path = Path(path)
            if failure_stage == "staging_validation" and ".restore." in candidate_path.name:
                raise DatabaseValidationError("staging validation fault")
            if (
                failure_stage in {
                    "post_validation", "rollback_copy",
                    "rollback_replace", "rollback_validation",
                }
                and candidate_path == active
                and replace_state["restore_published"]
                and replace_state["active_validations"] == 0
            ):
                replace_state["active_validations"] += 1
                raise DatabaseValidationError("post-replace validation fault")
            if failure_stage == "rollback_validation" and ".rollback." in candidate_path.name:
                raise DatabaseValidationError("rollback validation fault")
            return original_validate(path, **kwargs)

        monkeypatch.setattr(storage, "validate_database", injected_validate)

    with pytest.raises(Exception) as raised:
        restore_backup(url, candidate, safety_backup=safety)

    assert safety.is_file()
    original_validate(safety)
    original_validate(active)
    assert not list(tmp_path.glob(f".{active.name}.restore.*.tmp"))
    assert not list(tmp_path.glob(f".{active.name}.rollback.*.tmp"))

    active_connection = __import__("sqlite3").connect(str(active))
    try:
        newer_count = active_connection.execute(
            "SELECT count(*) FROM items WHERE name = 'Active newer item'"
        ).fetchone()[0]
    finally:
        active_connection.close()

    if failure_stage in {
        "candidate_copy", "staging_validation", "checkpoint", "replace",
        "post_validation",
    }:
        assert newer_count == 1
    else:
        assert newer_count == 0
        assert "rollback failed" in str(raised.value)
    if failure_stage == "post_validation":
        assert "rollback succeeded" in str(raised.value)


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


def test_backup_no_overwrite_race_preserves_concurrent_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ah_there_it_is.storage as storage

    active = tmp_path / "active.db"
    backup = tmp_path / "backup-race.db"
    normal_backup = tmp_path / "backup-normal.db"
    url = _migrate(active)
    _seed_operational_state(url)
    active_before = validate_database(active).sha256
    assert create_backup(url, normal_backup, overwrite=False).path == str(
        normal_backup.resolve()
    )
    validate_database(normal_backup)
    original_publish = storage._publish_backup_no_overwrite

    def inject_destination(source: Path, target: Path) -> None:
        target.write_bytes(b"concurrent backup owner")
        original_publish(source, target)

    monkeypatch.setattr(
        storage,
        "_publish_backup_no_overwrite",
        inject_destination,
    )
    with pytest.raises(StorageError, match="appeared during backup"):
        create_backup(url, backup, overwrite=False)

    assert backup.read_bytes() == b"concurrent backup owner"
    assert validate_database(active).sha256 == active_before
    assert not list(tmp_path.glob(".backup-race.db.backup.*.tmp"))


@pytest.mark.parametrize(
    ("failure_stage", "published"),
    [
        ("copy", False),
        ("validation", False),
        ("replace", False),
        ("file_fsync", True),
        ("directory_fsync", True),
    ],
)
def test_backup_overwrite_failure_atomicity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    published: bool,
) -> None:
    import ah_there_it_is.storage as storage

    active = tmp_path / f"active-{failure_stage}.db"
    backup = tmp_path / f"overwrite-{failure_stage}.db"
    url = _migrate(active)
    _seed_operational_state(url)
    create_backup(url, backup)
    old_bytes = backup.read_bytes()

    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            InventoryService(session).create_item(f"New state {failure_stage}")
    finally:
        engine.dispose()

    if failure_stage == "copy":
        monkeypatch.setattr(
            storage,
            "_copy_sqlite_snapshot",
            lambda _source, _target: (_ for _ in ()).throw(OSError("copy fault")),
        )
    elif failure_stage == "validation":
        original_validate = storage.validate_database

        def fail_candidate(path, **kwargs):
            if ".backup." in Path(path).name:
                raise DatabaseValidationError("validation fault")
            return original_validate(path, **kwargs)

        monkeypatch.setattr(storage, "validate_database", fail_candidate)
    elif failure_stage == "replace":
        monkeypatch.setattr(
            storage.os,
            "replace",
            lambda _source, _target: (_ for _ in ()).throw(OSError("replace fault")),
        )
    elif failure_stage == "file_fsync":
        monkeypatch.setattr(
            storage,
            "_fsync_path",
            lambda _path: (_ for _ in ()).throw(OSError("file fsync fault")),
        )
    else:
        monkeypatch.setattr(
            storage,
            "_fsync_directory",
            lambda _path: (_ for _ in ()).throw(OSError("directory fsync fault")),
        )

    with pytest.raises(StorageError) as raised:
        create_backup(url, backup, overwrite=True)
    assert not list(tmp_path.glob(f".{backup.name}.backup.*.tmp"))
    if published:
        assert "was published but durability sync failed" in str(raised.value)
        validate_database(backup)
        assert backup.read_bytes() != old_bytes
    else:
        assert backup.read_bytes() == old_bytes


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
    assert ch341a["location_status"] == "known"
    assert ch341a["attributes"]["model"] == "CH341A"
    assert "CH341A" in ch341a["aliases"]
    assert {"BIOS", "SPI", "flash"} <= set(ch341a["tags"])

    serialized = output.read_text(encoding="utf-8")
    assert "agent_run_logs" in loaded["excluded"]
    assert "experiment_runs" in loaded["excluded"]
    assert "llm_provider" not in serialized
    assert "tool_trace" not in serialized


def test_portable_export_projection_is_bounded_and_ordered(tmp_path: Path) -> None:
    active = tmp_path / "projection.db"
    url = _migrate(active)
    engine = create_db_engine(url)
    stamp = __import__("datetime").datetime(2020, 1, 1)
    try:
        with Session(engine) as session:
            session.execute(
                Item.__table__.insert(),
                [
                    {
                        "id": index,
                        "name": f"Item {index}",
                        "normalized_name": f"item {index}",
                        "description": None,
                        "state": "unknown",
                        "category_id": None,
                        "current_location_id": None,
                        "location_status": "unknown",
                        "quantity": 1,
                        "attributes": {"index": index},
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                    for index in range(1, 1001)
                ],
            )
            session.execute(
                Alias.__table__.insert(),
                [
                    {"id": 2, "item_id": 1, "name": "second", "normalized_name": "second"},
                    {"id": 1, "item_id": 1, "name": "first", "normalized_name": "first"},
                ],
            )
            session.execute(
                Tag.__table__.insert(),
                [
                    {"id": 2, "name": "tag-two", "normalized_name": "tag-two"},
                    {"id": 1, "name": "tag-one", "normalized_name": "tag-one"},
                ],
            )
            session.execute(
                ItemTag.__table__.insert(),
                [{"item_id": 1, "tag_id": 2}, {"item_id": 1, "tag_id": 1}],
            )
            session.commit()
            session.expunge_all()

            statements: list[str] = []
            listener = lambda *_args: statements.append(str(_args[2]))
            sqlalchemy_event.listen(engine, "before_cursor_execute", listener)
            document = _portable_document(session, CURRENT_SCHEMA_REVISION)
            sqlalchemy_event.remove(engine, "before_cursor_execute", listener)

            assert len(document["inventory"]["items"]) == 1000
            assert document["inventory"]["items"][0]["aliases"] == ["first", "second"]
            assert document["inventory"]["items"][0]["tags"] == ["tag-one", "tag-two"]
            assert len(statements) == 6
            assert not any(isinstance(row, Item) for row in session.identity_map.values())
    finally:
        engine.dispose()


def test_portable_export_stream_is_lazy_and_preserves_destination_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = io.StringIO()

    def rows():
        assert handle.getvalue() == "["
        yield {"name": "один"}
        assert handle.getvalue().startswith('[{"name":"один"}')
        yield {"name": "два"}

    assert _write_json_array(handle, rows()) == 2
    assert json.loads(handle.getvalue()) == [{"name": "один"}, {"name": "два"}]

    active = tmp_path / "stream.db"
    destination = tmp_path / "inventory.json"
    url = _migrate(active)
    _seed_operational_state(url)
    destination.write_bytes(b"keep-existing")

    import ah_there_it_is.storage as storage

    def fail_events(_session):
        raise RuntimeError("injected stream failure")
        yield

    monkeypatch.setattr(storage, "_stream_events", fail_events)
    with pytest.raises(RuntimeError, match="injected stream failure"):
        stream_portable_inventory(url, destination)
    assert destination.read_bytes() == b"keep-existing"
    assert list(tmp_path.glob(".inventory.json.json.*.tmp")) == []


def test_portable_export_stream_result_and_target_scale_are_complete(
    tmp_path: Path,
) -> None:
    active = tmp_path / "stream-scale.db"
    destination = tmp_path / "inventory.json"
    url = _migrate(active)
    engine = create_db_engine(url)
    stamp = __import__("datetime").datetime(2020, 1, 1)
    try:
        with Session(engine) as session:
            session.execute(
                Item.__table__.insert(),
                [
                    {
                        "id": index,
                        "name": f"Вещь {index}",
                        "normalized_name": f"вещь {index}",
                        "description": None,
                        "state": "unknown",
                        "category_id": None,
                        "current_location_id": None,
                        "location_status": "unknown",
                        "quantity": 1,
                        "attributes": {},
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                    for index in range(1, 1001)
                ],
            )
            session.commit()
    finally:
        engine.dispose()

    result = stream_portable_inventory(url, destination)
    loaded = json.loads(destination.read_text(encoding="utf-8"))
    assert result.items == 1000
    assert result.categories == result.locations == result.events == 0
    assert len(loaded["inventory"]["items"]) == 1000
    assert loaded["inventory"]["items"][0]["name"] == "Вещь 1"
    assert loaded["inventory"]["items"][-1]["id"] == 1000


def test_portable_export_snapshot_is_coherent_across_projection_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3
    import ah_there_it_is.storage as storage

    active = tmp_path / "snapshot.db"
    first_output = tmp_path / "snapshot-first.json"
    second_output = tmp_path / "snapshot-second.json"
    url = _migrate(active)
    writer = sqlite3.connect(str(active))
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("PRAGMA foreign_keys=ON")
    stamp = "2020-01-01 00:00:00"
    writer.execute(
        "INSERT INTO categories(id,parent_id,name,normalized_name,description,created_at,updated_at) "
        "VALUES (1,NULL,'Before category','before category',NULL,?,?)",
        (stamp, stamp),
    )
    writer.execute(
        "INSERT INTO locations(id,parent_id,name,normalized_name,description,created_at,updated_at) "
        "VALUES (1,NULL,'Before location','before location',NULL,?,?)",
        (stamp, stamp),
    )
    writer.execute(
        "INSERT INTO items(id,name,normalized_name,description,state,category_id,current_location_id,"
        "location_status,quantity,attributes,created_at,updated_at) "
        "VALUES (1,'Before item','before item',NULL,'working',1,1,'known',1,'{}',?,?)",
        (stamp, stamp),
    )
    writer.execute(
        "INSERT INTO events(id,event_type,item_id,from_location_id,to_location_id,payload,original_text,created_at) "
        "VALUES (1,'item_created',1,NULL,1,'{}',NULL,?)",
        (stamp,),
    )
    writer.commit()

    original_stream_trees = storage._stream_trees
    committed_bytes: dict[str, bytes] = {}

    def interleaved_stream_trees(session, model):
        yield from original_stream_trees(session, model)
        if model is Category and not committed_bytes:
            writer.execute(
                "INSERT INTO categories(id,parent_id,name,normalized_name,description,created_at,updated_at) "
                "VALUES (2,NULL,'After category','after category',NULL,?,?)",
                (stamp, stamp),
            )
            writer.execute(
                "INSERT INTO locations(id,parent_id,name,normalized_name,description,created_at,updated_at) "
                "VALUES (2,NULL,'After location','after location',NULL,?,?)",
                (stamp, stamp),
            )
            writer.execute(
                "INSERT INTO items(id,name,normalized_name,description,state,category_id,current_location_id,"
                "location_status,quantity,attributes,created_at,updated_at) "
                "VALUES (2,'After item','after item',NULL,'working',2,2,'known',1,'{}',?,?)",
                (stamp, stamp),
            )
            writer.execute(
                "INSERT INTO events(id,event_type,item_id,from_location_id,to_location_id,payload,original_text,created_at) "
                "VALUES (2,'item_created',2,NULL,2,'{}',NULL,?)",
                (stamp,),
            )
            writer.commit()
            committed_bytes["main"] = active.read_bytes()
            committed_bytes["wal"] = Path(str(active) + "-wal").read_bytes()

    monkeypatch.setattr(storage, "_stream_trees", interleaved_stream_trees)
    try:
        first = stream_portable_inventory(url, first_output)
        first_document = json.loads(first_output.read_text(encoding="utf-8"))
        assert first.categories == first.locations == first.items == first.events == 1
        assert [row["id"] for row in first_document["inventory"]["categories"]] == [1]
        assert [row["id"] for row in first_document["inventory"]["locations"]] == [1]
        assert [row["id"] for row in first_document["inventory"]["items"]] == [1]
        assert [row["id"] for row in first_document["history"]["events"]] == [1]
        assert active.read_bytes() == committed_bytes["main"]
        assert Path(str(active) + "-wal").read_bytes() == committed_bytes["wal"]

        monkeypatch.setattr(storage, "_stream_trees", original_stream_trees)
        second = stream_portable_inventory(url, second_output)
        assert second.categories == second.locations == second.items == second.events == 2
    finally:
        writer.close()


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
                    "location_status": "known",
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
    assert document.inventory.items[0].location_status == "known"
    assert document.history.events[0].to_location_id == 2


@pytest.mark.parametrize(
    "value",
    [None, "inventory-portable-v3", 12],
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


def test_portable_parser_rejects_every_duplicate_id_class() -> None:
    cases = [
        ("categories", "inventory", "category"),
        ("locations", "inventory", "location"),
        ("items", "inventory", "item"),
        ("events", "history", "event"),
    ]
    for section, container, label in cases:
        raw = _minimal_portable_document()
        values = raw[container][section]
        values.append(deepcopy(values[0]))
        with pytest.raises(
            PortableInventoryValidationError,
            match=rf"duplicate {label} id=",
        ):
            parse_portable_inventory(raw)


def test_portable_parser_rejects_every_reference_class() -> None:
    category_parent = _minimal_portable_document()
    category_parent["inventory"]["categories"][0]["parent_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing parent id=999"):
        parse_portable_inventory(category_parent)

    location_parent = _minimal_portable_document()
    location_parent["inventory"]["locations"][0]["parent_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing parent id=999"):
        parse_portable_inventory(location_parent)

    item_category = _minimal_portable_document()
    item_category["inventory"]["items"][0]["category_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing category id=999"):
        parse_portable_inventory(item_category)

    item_location = _minimal_portable_document()
    item_location["inventory"]["items"][0]["location_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing location id=999"):
        parse_portable_inventory(item_location)

    event_item = _minimal_portable_document()
    event_item["history"]["events"][0]["item_id"] = 999
    with pytest.raises(PortableInventoryValidationError, match="missing item id=999"):
        parse_portable_inventory(event_item)

    event_from = _minimal_portable_document()
    event_from["history"]["events"][0]["from_location_id"] = 999
    with pytest.raises(
        PortableInventoryValidationError,
        match=r"from_location_id references missing location id=999",
    ):
        parse_portable_inventory(event_from)

    event_to = _minimal_portable_document()
    event_to["history"]["events"][0]["to_location_id"] = 999
    with pytest.raises(
        PortableInventoryValidationError,
        match=r"to_location_id references missing location id=999",
    ):
        parse_portable_inventory(event_to)


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
    exported_evidence = {
        event["id"]: event["payload"]["_history_evidence"]
        for event in original["history"]["events"]
        if "_history_evidence" in event["payload"]
    }
    assert exported_evidence

    # An ambient active-DB override must not hijack Alembic during portable import.
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", url)
    result = import_portable_inventory(url, exported, imported)

    assert result.imported_path == str(imported.resolve())
    assert result.items == len(original["inventory"]["items"])
    assert validate_database(imported).alembic_revision == CURRENT_SCHEMA_REVISION

    # SQLite file bytes are not a logical-state invariant: opening/checkpointing
    # a WAL database may change physical pages or headers across SQLite builds.
    # Prove instead that the configured active database retained the same
    # portable domain state and its operational-only records.
    active_after = export_portable_inventory(
        url,
        tmp_path / "active-after-import.json",
    )
    assert _semantic_portable(active_after) == _semantic_portable(original)
    active_engine = create_db_engine(url)
    try:
        with Session(active_engine) as session:
            assert session.scalar(select(func.count(Conversation.id))) == 1
            assert session.scalar(select(func.count(ChatRequestRecord.id))) == 2
            assert SearchService(session).search_items("CH341A")[0].id == ids["ch341a"]
    finally:
        active_engine.dispose()

    imported_url = f"sqlite:///{imported}"
    engine = create_db_engine(imported_url)
    try:
        with Session(engine) as session:
            search = SearchService(session)
            assert search.search_items("SPI flash")[0].id == ids["ch341a"]
            assert search.search_items("CH341A")[0].id == ids["ch341a"]
            assert search.search_items("BIOS")[0].id == ids["ch341a"]

            imported_events = list(session.scalars(select(Event).order_by(Event.id)))
            event_ids = [event.id for event in imported_events]
            assert event_ids == [
                event["id"] for event in original["history"]["events"]
            ]
            imported_evidence = {
                event.id: event.payload["_history_evidence"]
                for event in imported_events
                if "_history_evidence" in event.payload
            }
            assert imported_evidence == exported_evidence
            assert session.scalar(select(func.count(Conversation.id))) == 0
            assert session.scalar(select(func.count(ChatRequestRecord.id))) == 0
    finally:
        engine.dispose()

    reconstructed = export_portable_inventory(imported_url, reexported)
    assert _semantic_portable(reconstructed) == _semantic_portable(original)
    reexported_evidence = {
        event["id"]: event["payload"]["_history_evidence"]
        for event in reconstructed["history"]["events"]
        if "_history_evidence" in event["payload"]
    }
    assert reexported_evidence == exported_evidence


def test_portable_roundtrip_target_scale_preserves_semantics(tmp_path: Path) -> None:
    active = tmp_path / "scale-active.db"
    exported = tmp_path / "scale-export.json"
    imported = tmp_path / "scale-imported.db"
    reexported = tmp_path / "scale-reexport.json"
    url = _migrate(active)
    engine = create_db_engine(url)
    stamp = __import__("datetime").datetime(2020, 1, 1)
    try:
        with Session(engine) as session:
            session.execute(
                Category.__table__.insert(),
                [
                    {
                        "id": index,
                        "parent_id": index - 1 if index % 10 != 1 else None,
                        "name": f"Category {index}",
                        "normalized_name": f"category {index}",
                        "description": None,
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                    for index in range(1, 121)
                ],
            )
            session.execute(
                Location.__table__.insert(),
                [
                    {
                        "id": index,
                        "parent_id": index - 1 if index % 10 != 1 else None,
                        "name": f"Location {index}",
                        "normalized_name": f"location {index}",
                        "description": None,
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                    for index in range(1, 121)
                ],
            )
            items = []
            for index in range(1, 1001):
                mode = index % 4
                state, location_status, location_id = (
                    ("sold", "not_applicable", None) if mode == 0
                    else ("working", "known", (index % 120) + 1) if mode == 1
                    else ("used", "in_use", None) if mode == 2
                    else ("unknown", "unknown", None)
                )
                items.append({
                    "id": index,
                    "name": f"Scale Item {index}",
                    "normalized_name": f"scale item {index}",
                    "description": f"Описание {index}",
                    "state": state,
                    "category_id": (index % 120) + 1,
                    "current_location_id": location_id,
                    "location_status": location_status,
                    "quantity": (index % 3) + 1,
                    "attributes": {"index": index, "group": index % 7},
                    "created_at": stamp,
                    "updated_at": stamp,
                })
            session.execute(Item.__table__.insert(), items)
            session.execute(
                Alias.__table__.insert(),
                [
                    {
                        "id": index,
                        "item_id": index,
                        "name": f"Alias {index}",
                        "normalized_name": f"alias {index}",
                    }
                    for index in range(1, 1001)
                ],
            )
            session.execute(
                Tag.__table__.insert(),
                [
                    {"id": index, "name": f"Tag {index}", "normalized_name": f"tag {index}"}
                    for index in range(1, 21)
                ],
            )
            session.execute(
                ItemTag.__table__.insert(),
                [
                    {"item_id": item_id, "tag_id": tag_id}
                    for item_id in range(1, 1001)
                    for tag_id in sorted({(item_id % 20) + 1, ((item_id + 7) % 20) + 1})
                ],
            )
            session.execute(
                Event.__table__.insert(),
                [
                    {
                        "id": index,
                        "event_type": "item_created",
                        "item_id": index,
                        "from_location_id": None,
                        "to_location_id": items[index - 1]["current_location_id"],
                        "payload": {"name": f"Scale Item {index}"},
                        "original_text": f"seed {index}",
                        "created_at": stamp,
                    }
                    for index in range(1, 1001)
                ],
            )
            session.execute(
                Conversation.__table__.insert(),
                [{"id": 1, "created_at": stamp, "updated_at": stamp}],
            )
            session.execute(
                AgentRunLog.__table__.insert(),
                [{
                    "id": 1, "conversation_id": 1, "user_message_id": None,
                    "assistant_message_id": None, "prompt_version": "excluded",
                    "prompt_hash": "x" * 64, "system_prompt": "excluded",
                    "llm_provider": "test", "llm_model": "excluded",
                    "llm_config": {}, "input_messages": [], "tool_trace": [],
                    "mutation_receipts": [], "final_content": "excluded",
                    "rounds": 1, "status": "completed", "error": None,
                    "created_at": stamp,
                }],
            )
            session.execute(
                ExperimentRun.__table__.insert(),
                [{
                    "id": 1, "source_run_id": 1, "experiment_name": "excluded",
                    "prompt_version": "excluded", "prompt_hash": "y" * 64,
                    "system_prompt": "excluded", "llm_provider": "test",
                    "llm_model": "excluded", "llm_config": {},
                    "input_messages": [], "tool_trace": [], "final_content": "excluded",
                    "rounds": 1, "status": "completed", "error": None,
                    "divergence_reason": None, "created_at": stamp,
                }],
            )
            session.commit()
    finally:
        engine.dispose()

    first = export_portable_inventory(url, exported)
    result = import_portable_inventory(url, exported, imported)
    second = export_portable_inventory(f"sqlite:///{imported}", reexported)

    assert _semantic_portable(first) == _semantic_portable(second)
    assert result.categories == result.locations == 120
    assert result.items == result.events == 1000
    assert [row["id"] for row in second["inventory"]["items"]] == list(range(1, 1001))
    assert validate_database(imported).integrity_check == ("ok",)
    assert diagnose_database(f"sqlite:///{imported}").ok is True

    imported_engine = create_db_engine(f"sqlite:///{imported}")
    try:
        with Session(imported_engine) as session:
            assert SearchService(session).search_items("Scale Item 1000")[0].id == 1000
            assert session.scalar(select(func.count(Conversation.id))) == 0
            assert session.scalar(select(func.count(AgentRunLog.id))) == 0
            assert session.scalar(select(func.count(ExperimentRun.id))) == 0
    finally:
        imported_engine.dispose()


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


def test_portable_import_batches_target_scale_and_rolls_back_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ah_there_it_is.storage as storage

    active = tmp_path / "active.db"
    source = tmp_path / "batch-import.json"
    destination = tmp_path / "batch-import.db"
    failed_destination = tmp_path / "failed-import.db"
    url = _migrate(active)
    raw = _minimal_portable_document()
    template = raw["inventory"]["items"][0]
    raw["inventory"]["items"] = [
        {
            **template,
            "id": index,
            "name": f"Batch Item {index}",
            "aliases": [f"Alias {index}"],
            "tags": [f"Tag {index % 20}", f"Tag {(index + 3) % 20}"],
            "attributes": {"index": index},
        }
        for index in range(1, 1001)
    ]
    raw["history"]["events"] = []
    source.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    statements: list[str] = []
    original_create_engine = storage.create_db_engine

    def observed_engine(database_url: str):
        engine = original_create_engine(database_url)
        sqlalchemy_event.listen(
            engine,
            "before_cursor_execute",
            lambda _connection, _cursor, statement, *_args: statements.append(statement),
        )
        return engine

    monkeypatch.setattr(storage, "create_db_engine", observed_engine)
    result = import_portable_inventory(url, source, destination)
    assert result.items == 1000
    insert_statements = [
        statement for statement in statements
        if statement.lstrip().upper().startswith("INSERT")
    ]
    assert len(insert_statements) < 40
    assert sum("INTO tags" in statement for statement in insert_statements) <= 1
    assert sum("INTO item_tags" in statement for statement in insert_statements) <= 1

    monkeypatch.setattr(
        storage,
        "_validate_imported_search_state",
        lambda _session: (_ for _ in ()).throw(RuntimeError("mid-import failure")),
    )
    with pytest.raises(RuntimeError, match="mid-import failure"):
        import_portable_inventory(url, source, failed_destination)
    assert not failed_destination.exists()
    assert not Path(str(failed_destination) + "-wal").exists()
    assert not Path(str(failed_destination) + "-shm").exists()


@pytest.mark.parametrize("race_path", ["main", "wal", "shm"])
def test_portable_import_publication_race_preserves_concurrent_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_path: str,
) -> None:
    import ah_there_it_is.storage as storage

    active = tmp_path / "active.db"
    source = tmp_path / "source.json"
    destination = tmp_path / "race.db"
    url = _migrate(active)
    _seed_operational_state(url)
    export_portable_inventory(url, source)
    active_before = validate_database(active).sha256
    source_before = source.read_bytes()
    original_publish = storage._publish_new_database
    raced = (
        destination if race_path == "main"
        else Path(str(destination) + f"-{race_path}")
    )

    def inject_race(publish: Path, target: Path) -> None:
        raced.write_bytes(f"concurrent-{race_path}".encode())
        original_publish(publish, target)

    monkeypatch.setattr(storage, "_publish_new_database", inject_race)
    with pytest.raises(StorageError, match="appeared"):
        import_portable_inventory(url, source, destination)

    assert raced.read_bytes() == f"concurrent-{race_path}".encode()
    if race_path != "main":
        assert not destination.exists()
    assert source.read_bytes() == source_before
    assert validate_database(active).sha256 == active_before
    assert not list(tmp_path.glob(".race.db.portable-*.tmp"))


def test_portable_import_publish_primitive_failure_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ah_there_it_is.storage as storage

    active = tmp_path / "active.db"
    source = tmp_path / "source.json"
    destination = tmp_path / "publish-failure.db"
    url = _migrate(active)
    _seed_operational_state(url)
    export_portable_inventory(url, source)
    monkeypatch.setattr(
        storage.os,
        "link",
        lambda _source, _target: (_ for _ in ()).throw(OSError("link failed")),
    )

    with pytest.raises(StorageError, match="cannot atomically publish"):
        import_portable_inventory(url, source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".publish-failure.db.portable-*.tmp"))


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


def test_portable_file_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    source = tmp_path / "duplicate-key.json"
    source.write_text(
        '{"format":"inventory-portable-v1","format":"inventory-portable-v1"}',
        encoding="utf-8",
    )

    from ah_there_it_is.storage import validate_portable_inventory

    with pytest.raises(PortableInventoryValidationError, match="duplicate JSON object key"):
        validate_portable_inventory(source)
