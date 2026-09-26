"""A release rollback is separate from strict same-schema restore."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.storage import DatabaseValidationError, restore_backup, validate_database
from deploy.cross_schema_rollback import rollback_cross_schema
from deploy import cross_schema_rollback


OLD_REVISION = "1a7c4e9d2b10"


def _old_validator(path: Path) -> None:
    validate_database(path, expected_revision=OLD_REVISION)


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    active = tmp_path / "active.db"
    candidate = tmp_path / "pre-upgrade.db"
    upgrade_database(f"sqlite:///{active}", OLD_REVISION)
    with sqlite3.connect(active) as source, sqlite3.connect(candidate) as destination:
        source.backup(destination)
    _old_validator(candidate)
    upgrade_database(f"sqlite:///{active}")
    return active, candidate


def test_cross_schema_release_rollback_preserves_upgraded_safety_and_old_data(
    tmp_path: Path,
) -> None:
    active, candidate = _setup(tmp_path)
    safety = tmp_path / "upgraded-safety.db"
    with pytest.raises(DatabaseValidationError):
        restore_backup(f"sqlite:///{active}", candidate)

    result = rollback_cross_schema(
        f"sqlite:///{active}", candidate,
        expected_old_revision=OLD_REVISION,
        validate_old=_old_validator,
        safety_backup=safety,
        require_stopped=lambda: None,
    )

    assert result["old_revision"] == OLD_REVISION
    assert result["upgraded_safety_backup"] == str(safety)
    assert not Path(f"{active}-wal").exists()
    assert not Path(f"{active}-shm").exists()
    _old_validator(active)
    _old_validator(candidate)
    validate_database(safety)
    validate_database(Path(result["upgraded_quarantine"]) / active.name)


def test_cross_schema_rollback_refuses_existing_safety_backup(tmp_path: Path) -> None:
    active, candidate = _setup(tmp_path)
    safety = tmp_path / "upgraded-safety.db"
    safety.write_bytes(b"other backup owner")

    with pytest.raises(Exception, match="already exists"):
        rollback_cross_schema(
            f"sqlite:///{active}", candidate,
            expected_old_revision=OLD_REVISION,
            validate_old=_old_validator,
            safety_backup=safety,
            require_stopped=lambda: None,
        )

    assert safety.read_bytes() == b"other backup owner"
    validate_database(active)


def test_cross_schema_publish_refuses_competing_active_file(
    tmp_path: Path, monkeypatch,
) -> None:
    active, candidate = _setup(tmp_path)
    safety = tmp_path / "upgraded-safety.db"
    original_link = cross_schema_rollback.os.link

    def competing_link(source, destination):
        if Path(destination) == active:
            active.write_bytes(b"competing owner")
        return original_link(source, destination)

    monkeypatch.setattr(cross_schema_rollback.os, "link", competing_link)
    with pytest.raises(FileExistsError):
        rollback_cross_schema(
            f"sqlite:///{active}", candidate,
            expected_old_revision=OLD_REVISION,
            validate_old=_old_validator,
            safety_backup=safety,
            require_stopped=lambda: None,
        )

    assert active.read_bytes() == b"competing owner"
    validate_database(safety)
    quarantines = list(tmp_path.glob("active.db.upgraded-*"))
    assert len(quarantines) == 1
    validate_database(quarantines[0] / active.name)


def test_cross_schema_move_failure_restores_upgraded_active(
    tmp_path: Path, monkeypatch,
) -> None:
    active, candidate = _setup(tmp_path)
    safety = tmp_path / "upgraded-safety.db"
    original_replace = cross_schema_rollback.os.replace

    def failed_active_move(source, destination):
        if Path(source) == active:
            raise OSError("simulated active move failure")
        return original_replace(source, destination)

    monkeypatch.setattr(cross_schema_rollback.os, "replace", failed_active_move)
    with pytest.raises(OSError, match="simulated active move failure"):
        rollback_cross_schema(
            f"sqlite:///{active}", candidate,
            expected_old_revision=OLD_REVISION,
            validate_old=_old_validator,
            safety_backup=safety,
            require_stopped=lambda: None,
        )

    validate_database(active)
    validate_database(safety)


def test_automatic_backup_naming_is_repeatable_without_overwrite(tmp_path: Path) -> None:
    active = tmp_path / "active.db"
    upgrade_database(f"sqlite:///{active}")
    backups = tmp_path / "backups"
    environment = {
        **os.environ,
        "AH_THERE_IT_IS_ENV": "production",
        "AH_THERE_IT_IS_DATABASE_URL": f"sqlite:///{active}",
    }
    paths = []
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-m", "ah_there_it_is.storage_cli", "backup-auto", str(backups)],
            env=environment, capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        path = Path(json.loads(result.stdout)["path"])
        validate_database(path)
        paths.append(path)
    assert paths[0] != paths[1]
    assert all(path.is_file() for path in paths)
