# test_restore_rehearsal.py
"""Restore candidate rehearsal against a disposable, current-schema target."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import pytest

from ah_there_it_is import storage
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.storage import create_backup, rehearse_restore, validate_database
from ah_there_it_is.storage_cli import main as storage_cli_main
from sqlalchemy.orm import Session


def prepared(tmp_path: Path) -> tuple[Path, str, Path]:
    active = tmp_path / "active.db"
    candidate = tmp_path / "candidate.db"
    url = f"sqlite:///{active}"
    upgrade_database(url)
    engine = create_db_engine(url)
    try:
        with Session(engine) as session:
            InventoryService(session).create_item("Healthy meter")
    finally:
        engine.dispose()
    create_backup(url, candidate)
    return active, url, candidate


def active_files(active: Path) -> dict[str, bytes]:
    return {
        name: path.read_bytes()
        for name in ("", "-wal", "-shm")
        if (path := Path(str(active) + name)).exists()
    }


def assert_workspace_clean(tmp_path: Path) -> None:
    assert not list(tmp_path.glob("ah-restore-rehearsal-*"))


def test_healthy_rehearsal_preserves_active_wal_and_cleans_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    active, url, candidate = prepared(tmp_path)
    monkeypatch.setattr(storage.tempfile, "tempdir", str(tmp_path))
    writer = sqlite3.connect(active)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute(
            "INSERT INTO items(name, normalized_name, state, quantity, attributes, created_at, updated_at) "
            "VALUES('WAL meter', 'wal meter', 'unknown', 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        writer.commit()
        assert Path(str(active) + "-wal").stat().st_size > 0
        before = active_files(active)
        result = rehearse_restore(url, candidate)
        assert result["ok"] is True
        assert result["restore_mechanics"]["ok"] is True
        physical = result["physical_validation"]
        assert physical["ok"] is True
        assert physical["restored"]["integrity_check"] == ("ok",)
        assert physical["restored"]["foreign_key_violations"] == ()
        assert result["doctor"]["ok"] is True
        assert result["doctor"]["report"]["counts"]["items"] == 1
        assert active_files(active) == before
        assert_workspace_clean(tmp_path)
    finally:
        writer.close()


def test_invalid_and_wrong_revision_candidates_report_physical_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    active, url, candidate = prepared(tmp_path)
    monkeypatch.setattr(storage.tempfile, "tempdir", str(tmp_path))
    before = active_files(active)
    invalid = tmp_path / "invalid.db"
    invalid.write_bytes(b"not a SQLite database")
    invalid_result = rehearse_restore(url, invalid)
    assert invalid_result["ok"] is False
    assert invalid_result["restore_mechanics"]["ok"] is False
    assert invalid_result["physical_validation"]["ok"] is False
    assert invalid_result["doctor"]["ok"] is None
    assert_workspace_clean(tmp_path)

    with sqlite3.connect(candidate) as connection:
        connection.execute("UPDATE alembic_version SET version_num='older-revision'")
    wrong = rehearse_restore(url, candidate)
    assert wrong["ok"] is False
    assert wrong["restore_mechanics"]["ok"] is False
    assert wrong["physical_validation"]["ok"] is False
    assert "revision" in wrong["physical_validation"]["error"]
    assert wrong["doctor"]["ok"] is None
    assert active_files(active) == before
    assert_workspace_clean(tmp_path)


def test_semantically_unhealthy_candidate_fails_after_successful_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    active, url, candidate = prepared(tmp_path)
    monkeypatch.setattr(storage.tempfile, "tempdir", str(tmp_path))
    with sqlite3.connect(candidate) as connection:
        connection.execute("UPDATE items SET normalized_name='wrong' WHERE name='Healthy meter'")
    validate_database(candidate)
    before = active_files(active)
    result = rehearse_restore(url, candidate)
    assert result["ok"] is False
    assert result["restore_mechanics"]["ok"] is True
    assert result["physical_validation"]["ok"] is True
    assert result["doctor"]["ok"] is False
    assert result["doctor"]["report"]["checks"]["items_normalized_names"]["status"] == "error"
    assert active_files(active) == before
    assert_workspace_clean(tmp_path)


def test_wal_candidate_uses_snapshot_instead_of_raw_file_copy(tmp_path: Path) -> None:
    active, url, candidate = prepared(tmp_path)
    with sqlite3.connect(candidate) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute(
            "INSERT INTO items(name, normalized_name, state, quantity, attributes, created_at, updated_at) "
            "VALUES('Candidate WAL item', 'candidate wal item', 'unknown', 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        writer.commit()
        assert Path(str(candidate) + "-wal").stat().st_size > 0
        before = active_files(active)
        result = rehearse_restore(url, candidate)
        assert result["ok"] is True
        assert result["doctor"]["report"]["counts"]["items"] == 2
        assert active_files(active) == before


def test_active_path_as_candidate_is_rejected_without_sidecars(tmp_path: Path) -> None:
    active, url, _ = prepared(tmp_path)
    before = active_files(active)
    result = rehearse_restore(url, active)
    assert result["ok"] is False
    assert result["restore_mechanics"]["ok"] is False
    assert "must differ" in result["restore_mechanics"]["error"]
    assert active_files(active) == before


def test_storage_cli_exit_status_and_json(tmp_path: Path, monkeypatch, capsys) -> None:
    active, url, candidate = prepared(tmp_path)
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", url)
    monkeypatch.setattr(sys, "argv", ["storage_cli", "restore-rehearsal", str(candidate)])
    assert storage_cli_main() == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"bad")
    monkeypatch.setattr(sys, "argv", ["storage_cli", "restore-rehearsal", str(bad)])
    assert storage_cli_main() == 2
    assert json.loads(capsys.readouterr().out)["physical_validation"]["ok"] is False
    assert active.is_file()
