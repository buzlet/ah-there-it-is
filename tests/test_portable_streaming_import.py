from __future__ import annotations

import io
import json
from pathlib import Path
import sys

import pytest
from sqlalchemy import event as sqlalchemy_event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import Alias, Category, Event, Item, ItemTag, Location, Tag
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.config import Settings
from ah_there_it_is.portable_stream import (
    PortableInputError,
    SpoolMarker,
    read_portable_workspace,
)
from ah_there_it_is.storage import (
    PortableInventoryValidationError,
    _write_portable_workspace_inventory,
    _write_portable_workspace_events,
    import_portable_inventory,
    validate_portable_workspace,
)


def _document(*, events: int = 2) -> dict:
    return {
        "format": "inventory-portable-v2",
        "exported_at": "2026-09-25T00:00:00+00:00",
        "source": {"alembic_revision": "a4b7c9d2e610"},
        "inventory": {
            "categories": [],
            "locations": [],
            "items": [{"id": 1, "payload": {"nested": True}}],
        },
        "history": {
            "events": [
                {"id": index, "payload": {"body": "x" * 2048}}
                for index in range(1, events + 1)
            ]
        },
        "excluded": ["agent_run_logs"],
    }


def _valid_document() -> dict:
    stamp = "2026-09-25T00:00:00+00:00"
    return {
        "format": "inventory-portable-v2",
        "exported_at": stamp,
        "source": {"alembic_revision": "a4b7c9d2e610"},
        "inventory": {
            "categories": [
                {
                    "id": 2, "parent_id": 1, "name": "Child",
                    "description": None, "created_at": stamp, "updated_at": stamp,
                },
                {
                    "id": 1, "parent_id": None, "name": "Root",
                    "description": None, "created_at": stamp, "updated_at": stamp,
                },
            ],
            "locations": [
                {
                    "id": 1, "parent_id": None, "name": "Office",
                    "description": None, "created_at": stamp, "updated_at": stamp,
                }
            ],
            "items": [
                {
                    "id": 1, "name": "Meter", "description": None,
                    "state": "working", "category_id": 2, "location_id": 1,
                    "location_status": "known", "quantity": 1,
                    "attributes": {"range": "auto"}, "aliases": ["DMM"],
                    "tags": ["Tools"], "created_at": stamp, "updated_at": stamp,
                }
            ],
        },
        "history": {
            "events": [
                {
                    "id": 1, "event_type": "item_created", "item_id": 1,
                    "from_location_id": None, "to_location_id": 1,
                    "payload": {"name": "Meter"}, "original_text": "add meter",
                    "created_at": stamp,
                }
            ]
        },
        "excluded": ["agent_run_logs"],
    }


class _TrackingBytes(io.BytesIO):
    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_sizes: list[int] = []
        self.eof_observed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        value = super().read(size)
        if not value:
            self.eof_observed = True
        return value


def test_reader_spools_before_eof_with_bounded_reads(tmp_path: Path) -> None:
    source = tmp_path / "large.json"
    encoded = json.dumps(_document(events=80)).encode()
    source.write_bytes(encoded)
    tracking = _TrackingBytes(encoded)
    observations: list[tuple[str, int, bool]] = []

    with read_portable_workspace(
        source,
        chunk_size=127,
        workspace_parent=tmp_path,
        _open_binary=lambda _path: tracking,
        _on_spooled=lambda section, index: observations.append(
            (section, index, tracking.eof_observed)
        ),
    ) as workspace:
        assert workspace.counts["events"] == 80
        assert [event["id"] for event in workspace.iter_records("events")] == list(
            range(1, 81)
        )
        assert isinstance(workspace.structure["history"]["events"], SpoolMarker)
        root = workspace.root

    assert observations[0] == ("items", 0, False)
    assert any(section == "events" and index == 0 and not eof for section, index, eof in observations)
    assert tracking.read_sizes and set(tracking.read_sizes) == {127}
    assert not root.exists()


def test_reader_accepts_alternate_member_order(tmp_path: Path) -> None:
    original = _document(events=3)
    reordered = {
        "history": original["history"],
        "excluded": original["excluded"],
        "inventory": {
            "items": original["inventory"]["items"],
            "locations": [],
            "categories": [],
        },
        "source": original["source"],
        "exported_at": original["exported_at"],
        "format": original["format"],
    }
    source = tmp_path / "reordered.json"
    source.write_text(json.dumps(reordered), encoding="utf-8")

    with read_portable_workspace(source, chunk_size=23) as workspace:
        assert workspace.structure["format"] == "inventory-portable-v2"
        assert workspace.counts == {
            "categories": 0,
            "locations": 0,
            "items": 1,
            "events": 3,
        }


@pytest.mark.parametrize(
    "fragment",
    [
        '{"id":1,"payload":{"same":1,"same":2}}',
        '{"id":1,"payload":{"nested":{"same":1,"same":2}}}',
    ],
)
def test_reader_rejects_nested_duplicate_keys(tmp_path: Path, fragment: str) -> None:
    source = tmp_path / "duplicate.json"
    source.write_text(
        '{"format":"inventory-portable-v2","exported_at":"2026",'
        '"source":{},"inventory":{"categories":[],"locations":[],"items":['
        + fragment
        + ']},"history":{"events":[]},"excluded":[]}',
        encoding="utf-8",
    )

    with pytest.raises(PortableInputError, match="duplicate object key 'same'"):
        with read_portable_workspace(source, chunk_size=17):
            pass


def test_malformed_late_json_cleans_spool_workspace(tmp_path: Path) -> None:
    source = tmp_path / "late-malformed.json"
    encoded = json.dumps(_document(events=20))
    source.write_text(encoded[:-2], encoding="utf-8")

    with pytest.raises(PortableInputError, match="unexpected end|expected"):
        with read_portable_workspace(source, workspace_parent=tmp_path, chunk_size=31):
            pass

    assert not list(tmp_path.glob("ah-portable-input-*"))


def test_streaming_semantic_validation_returns_compact_summary(tmp_path: Path) -> None:
    source = tmp_path / "valid.json"
    source.write_text(json.dumps(_valid_document()), encoding="utf-8")

    with read_portable_workspace(source, chunk_size=29) as workspace:
        summary = validate_portable_workspace(workspace)

    assert summary.format == "inventory-portable-v2"
    assert summary.source_alembic_revision == "a4b7c9d2e610"
    assert summary.as_dict() == {
        "format": "inventory-portable-v2",
        "source_alembic_revision": "a4b7c9d2e610",
        "categories": 2,
        "locations": 1,
        "items": 1,
        "events": 1,
    }
    assert not hasattr(summary, "inventory")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda raw: raw["inventory"]["items"].append(dict(raw["inventory"]["items"][0])), "duplicate item"),
        (lambda raw: raw["inventory"]["items"][0].update(category_id=999), "missing category"),
        (lambda raw: raw["history"]["events"][0].update(item_id=999), "missing item"),
        (lambda raw: raw["inventory"]["categories"][1].update(parent_id=2), "hierarchy cycle"),
        (lambda raw: raw["inventory"]["items"][0].update(aliases=["DMM", " dmm "]), "duplicate normalized"),
    ],
)
def test_streaming_semantic_validation_rejects_invariants(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    raw = _valid_document()
    mutation(raw)
    source = tmp_path / "invalid-semantic.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    with read_portable_workspace(source) as workspace:
        with pytest.raises(PortableInventoryValidationError, match=message):
            validate_portable_workspace(workspace)


def test_streaming_validation_rejects_extra_fields(tmp_path: Path) -> None:
    raw = _valid_document()
    raw["inventory"]["items"][0]["unexpected"] = True
    source = tmp_path / "extra.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    with read_portable_workspace(source) as workspace:
        with pytest.raises(PortableInventoryValidationError, match="Extra inputs"):
            validate_portable_workspace(workspace)


def test_inventory_write_uses_bounded_batches_without_identity_growth(
    tmp_path: Path,
) -> None:
    raw = _valid_document()
    stamp = raw["exported_at"]
    raw["inventory"]["items"] = [
        {
            "id": index,
            "name": f"Item {index}",
            "description": f"Description {index}",
            "state": "working",
            "category_id": 2,
            "location_id": 1,
            "location_status": "known",
            "quantity": 1,
            "attributes": {"index": index},
            "aliases": [f"Alias {index}"],
            "tags": [f"Tag {index % 17}", "Common"],
            "created_at": stamp,
            "updated_at": stamp,
        }
        for index in range(1, 1001)
    ]
    raw["history"]["events"] = []
    source = tmp_path / "inventory-write.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    database = tmp_path / "working.db"
    url = f"sqlite:///{database}"
    upgrade_database(url)
    engine = create_db_engine(url)
    statements: list[str] = []
    sqlalchemy_event.listen(
        engine,
        "before_cursor_execute",
        lambda _connection, _cursor, statement, *_args: statements.append(statement),
    )
    batches: list[tuple[str, int]] = []
    try:
        with read_portable_workspace(source) as workspace:
            summary = validate_portable_workspace(workspace)
            with Session(engine) as session, session.begin():
                _write_portable_workspace_inventory(
                    session,
                    workspace,
                    summary,
                    batch_size=127,
                    _observe_batch=lambda section, size: batches.append((section, size)),
                )
                assert len(session.identity_map) == 0
        with Session(engine) as session:
            assert session.scalar(select(func.count(Item.id))) == 1000
            assert session.scalar(select(func.count(Alias.id))) == 1000
            assert session.scalar(select(func.count(Tag.id))) == 18
            assert session.scalar(select(func.count(ItemTag.item_id))) == 2000
            assert session.scalar(select(func.count(Category.id))) == 2
            assert session.scalar(select(func.count(Location.id))) == 1
    finally:
        engine.dispose()

    assert batches
    assert max(size for _section, size in batches) <= 127
    inserts = [statement for statement in statements if statement.lstrip().upper().startswith("INSERT")]
    assert len(inserts) < 40


def test_history_event_write_is_bounded_and_preserves_fields(tmp_path: Path) -> None:
    raw = _valid_document()
    stamp = raw["exported_at"]
    raw["history"]["events"] = [
        {
            "id": index,
            "event_type": "item_updated",
            "item_id": 1,
            "from_location_id": 1 if index % 2 else None,
            "to_location_id": None if index % 2 else 1,
            "payload": {"index": index, "body": "x" * 2048},
            "original_text": f"event {index} " + "y" * 512,
            "created_at": stamp,
        }
        for index in range(300, 0, -1)
    ]
    source = tmp_path / "history.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    database = tmp_path / "history.db"
    url = f"sqlite:///{database}"
    upgrade_database(url)
    engine = create_db_engine(url)
    batches: list[tuple[str, int]] = []
    try:
        with read_portable_workspace(source) as workspace:
            summary = validate_portable_workspace(workspace)
            with Session(engine) as session, session.begin():
                _write_portable_workspace_inventory(session, workspace, summary)
                _write_portable_workspace_events(
                    session,
                    workspace,
                    batch_size=113,
                    _observe_batch=lambda section, size: batches.append((section, size)),
                )
                assert len(session.identity_map) == 0
        with Session(engine) as session:
            assert session.scalar(select(func.count(Event.id))) == 300
            first = session.get(Event, 1)
            last = session.get(Event, 300)
            assert first.payload == {"index": 1, "body": "x" * 2048}
            assert first.original_text == "event 1 " + "y" * 512
            assert (last.from_location_id, last.to_location_id) == (None, 1)
    finally:
        engine.dispose()

    assert batches and max(size for section, size in batches if section == "events") <= 113


def test_late_history_event_failure_rolls_back_inventory_and_events(tmp_path: Path) -> None:
    raw = _valid_document()
    event = raw["history"]["events"][0]
    raw["history"]["events"] = [
        {**event, "id": index, "payload": {"index": index, "body": "z" * 1024}}
        for index in range(1, 101)
    ]
    source = tmp_path / "late-history-failure.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    database = tmp_path / "rollback.db"
    url = f"sqlite:///{database}"
    upgrade_database(url)
    engine = create_db_engine(url)
    observed = 0

    def fail_late(section: str, _size: int) -> None:
        nonlocal observed
        if section == "events":
            observed += 1
            if observed == 7:
                raise RuntimeError("late event write failure")

    try:
        with read_portable_workspace(source) as workspace:
            summary = validate_portable_workspace(workspace)
            with pytest.raises(RuntimeError, match="late event write failure"):
                with Session(engine) as session, session.begin():
                    _write_portable_workspace_inventory(session, workspace, summary)
                    _write_portable_workspace_events(
                        session,
                        workspace,
                        batch_size=10,
                        _observe_batch=fail_late,
                    )
        with Session(engine) as session:
            assert session.scalar(select(func.count(Item.id))) == 0
            assert session.scalar(select(func.count(Event.id))) == 0
            assert session.scalar(select(func.count(Category.id))) == 0
    finally:
        engine.dispose()


def test_portable_import_integration_never_uses_complete_document_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ah_there_it_is.storage as storage

    source = tmp_path / "bounded-import.json"
    source.write_text(json.dumps(_valid_document()), encoding="utf-8")
    active = tmp_path / "active.db"
    destination = tmp_path / "destination.db"
    active_url = f"sqlite:///{active}"
    upgrade_database(active_url)
    monkeypatch.setattr(
        storage,
        "load_portable_inventory",
        lambda _source: (_ for _ in ()).throw(AssertionError("complete parser used")),
    )

    result = import_portable_inventory(active_url, source, destination)

    assert result.items == result.events == 1
    assert result.categories == 2
    assert result.locations == 1
    assert destination.is_file()


def test_portable_import_validation_failure_precedes_destination_creation(
    tmp_path: Path,
) -> None:
    raw = _valid_document()
    raw["inventory"]["items"][0]["category_id"] = 999
    source = tmp_path / "invalid-before-working.json"
    source.write_text(json.dumps(raw), encoding="utf-8")
    active = tmp_path / "active.db"
    active_url = f"sqlite:///{active}"
    upgrade_database(active_url)
    destination = tmp_path / "absent-parent" / "destination.db"

    with pytest.raises(PortableInventoryValidationError, match="missing category"):
        import_portable_inventory(active_url, source, destination)

    assert not destination.parent.exists()


def test_portable_dry_run_is_bounded_and_database_pure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ah_there_it_is import portable_stream, storage, storage_cli

    source = tmp_path / "dry-run.json"
    source.write_text(json.dumps(_valid_document()), encoding="utf-8")
    active = tmp_path / "active.db"
    active_url = f"sqlite:///{active}"
    upgrade_database(active_url)
    destination = tmp_path / "absent" / "destination.db"
    before = active.read_bytes()
    monkeypatch.setattr(portable_stream.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(storage_cli, "get_settings", lambda: Settings(database_url=active_url))
    monkeypatch.setattr(
        storage,
        "validate_portable_inventory",
        lambda _source: (_ for _ in ()).throw(AssertionError("complete validator used")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["storage_cli", "import-json", str(source), str(destination), "--dry-run"],
    )

    assert storage_cli.main() == 0
    result = json.loads(capsys.readouterr().out)

    assert result["dry_run"] is True
    assert result["format"] == "inventory-portable-v2"
    assert result["categories"] == 2
    assert result["locations"] == result["items"] == result["events"] == 1
    assert active.read_bytes() == before
    assert not destination.parent.exists()
    assert not Path(str(destination) + "-wal").exists()
    assert not Path(str(destination) + "-shm").exists()
    assert not list(tmp_path.glob("ah-portable-input-*"))


def test_portable_v1_fixture_uses_bounded_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ah_there_it_is import storage_cli

    fixture = Path(__file__).parent / "fixtures" / "inventory-portable-v1.json"
    active = tmp_path / "active.db"
    active_url = f"sqlite:///{active}"
    upgrade_database(active_url)
    destination = tmp_path / "v1-import.db"
    monkeypatch.setattr(storage_cli, "get_settings", lambda: Settings(database_url=active_url))
    monkeypatch.setattr(
        sys,
        "argv",
        ["storage_cli", "import-json", str(fixture), str(destination), "--dry-run"],
    )

    assert storage_cli.main() == 0
    result = json.loads(capsys.readouterr().out)

    assert result["format"] == "inventory-portable-v1"
    assert result["source_alembic_revision"] == "c4cfe3a3e921"
    assert result["items"] == result["events"] == 3
    assert not destination.exists()


def _large_portable_document() -> dict:
    stamp = "2026-09-25T00:00:00+00:00"
    locations = [
        {
            "id": index,
            "parent_id": index - 1 if index % 10 != 1 else None,
            "name": f"Location {index}",
            "description": f"Location description {index}",
            "created_at": stamp,
            "updated_at": stamp,
        }
        for index in range(120, 0, -1)
    ]
    categories = [
        {
            "id": index,
            "parent_id": index - 1 if index % 5 != 1 else None,
            "name": f"Category {index}",
            "description": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        for index in range(30, 0, -1)
    ]
    items = []
    for index in range(1000, 0, -1):
        mode = index % 4
        state, location_status, location_id = (
            ("working", "known", (index % 120) + 1)
            if mode == 0
            else ("unknown", "unknown", None)
            if mode == 1
            else ("used", "in_use", None)
            if mode == 2
            else ("sold", "not_applicable", None)
        )
        items.append(
            {
                "id": index,
                "name": f"Scale Item {index}",
                "description": f"Scale description {index}",
                "state": state,
                "category_id": (index % 30) + 1,
                "location_id": location_id,
                "location_status": location_status,
                "quantity": (index % 3) + 1,
                "attributes": {"index": index, "group": index % 11},
                "aliases": [f"Alias {index}"],
                "tags": [f"Tag {index % 23}", "Scale"],
                "created_at": stamp,
                "updated_at": stamp,
            }
        )
    events = [
        {
            "id": index,
            "event_type": "scale_event",
            "item_id": (index % 1000) + 1,
            "from_location_id": None,
            "to_location_id": (index % 120) + 1,
            "payload": {"index": index, "body": "payload-" + "x" * 128},
            "original_text": f"event {index} " + "y" * 64,
            "created_at": stamp,
        }
        for index in range(10000, 0, -1)
    ]
    return {
        "history": {"events": events},
        "excluded": [
            "agent_run_logs", "agent_feedback", "experiment_runs",
            "experiment_reviews", "provider_metadata",
        ],
        "inventory": {
            "items": items,
            "locations": locations,
            "categories": categories,
        },
        "source": {"alembic_revision": "a4b7c9d2e610"},
        "exported_at": stamp,
        "format": "inventory-portable-v2",
    }


def _portable_semantics(value: dict) -> dict:
    normalized = json.loads(json.dumps(value))
    normalized.pop("exported_at", None)
    normalized["source"].pop("alembic_revision", None)
    if normalized["format"] == "inventory-portable-v2":
        normalized["format"] = "inventory-portable-v3"
        for item in normalized["inventory"]["items"]:
            item["quantity_mode"] = "exact"
            if item["state"] in {"sold", "discarded"}:
                item["removal_reason"] = item["state"]
                item["state"] = "removed"
            else:
                item["removal_reason"] = None
    for section in ("categories", "locations", "items"):
        normalized["inventory"][section].sort(key=lambda row: row["id"])
    normalized["history"]["events"].sort(key=lambda row: row["id"])
    for item in normalized["inventory"]["items"]:
        item["aliases"].sort(key=str.casefold)
        item["tags"].sort(key=str.casefold)
    return normalized


@pytest.mark.extended
def test_portable_target_scale_bounded_roundtrip_and_late_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ah_there_it_is import portable_stream, storage, storage_cli

    raw = _large_portable_document()
    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode()
    source = tmp_path / "large-portable.json"
    source.write_bytes(encoded)
    active = tmp_path / "active.db"
    active_url = f"sqlite:///{active}"
    upgrade_database(active_url)
    imported = tmp_path / "large-imported.db"
    reexported = tmp_path / "large-reexported.json"
    trackers: list[_TrackingBytes] = []
    original_open = Path.open

    def tracked_open(path: Path, mode: str = "r", *args, **kwargs):
        if path.resolve() == source.resolve() and mode == "rb":
            tracker = _TrackingBytes(encoded)
            trackers.append(tracker)
            return tracker
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setattr(portable_stream.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(storage_cli, "get_settings", lambda: Settings(database_url=active_url))
    monkeypatch.setattr(
        storage,
        "load_portable_inventory",
        lambda _source: (_ for _ in ()).throw(AssertionError("complete parser used")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["storage_cli", "import-json", str(source), str(imported), "--dry-run"],
    )
    assert storage_cli.main() == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["locations"] == 120
    assert dry_run["categories"] == 30
    assert dry_run["items"] == 1000
    assert dry_run["events"] == 10000

    result = import_portable_inventory(active_url, source, imported)
    assert (result.locations, result.categories, result.items, result.events) == (
        120, 30, 1000, 10000,
    )
    from ah_there_it_is.storage import export_portable_inventory

    reconstructed = export_portable_inventory(f"sqlite:///{imported}", reexported)
    assert _portable_semantics(reconstructed) == _portable_semantics(raw)
    assert trackers and all(
        size == 64 * 1024
        for tracker in trackers
        for size in tracker.read_sizes
    )

    late_source = tmp_path / "large-late-invalid.json"
    late_source.write_bytes(encoded[:-1])
    late_destination = tmp_path / "large-late-failed.db"
    active_before = active.read_bytes()
    source_before = late_source.read_bytes()
    with pytest.raises(PortableInventoryValidationError, match="unexpected end|expected"):
        import_portable_inventory(active_url, late_source, late_destination)
    assert not late_destination.exists()
    assert active.read_bytes() == active_before
    assert late_source.read_bytes() == source_before
    assert not list(tmp_path.glob("ah-portable-input-*"))
    assert not list(tmp_path.glob(".large-late-failed.db.portable-*.tmp"))
