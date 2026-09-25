from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from sqlalchemy import event as sqlalchemy_event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import Alias, Category, Item, ItemTag, Location, Tag
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.portable_stream import (
    PortableInputError,
    SpoolMarker,
    read_portable_workspace,
)
from ah_there_it_is.storage import (
    PortableInventoryValidationError,
    _write_portable_workspace_inventory,
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
