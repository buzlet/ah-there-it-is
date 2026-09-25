from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ah_there_it_is.portable_stream import (
    PortableInputError,
    SpoolMarker,
    read_portable_workspace,
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
