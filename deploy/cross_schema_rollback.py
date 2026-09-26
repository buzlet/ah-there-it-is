"""Explicit stopped-service rollback from a pre-upgrade SQLite backup."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Callable
from uuid import uuid4

from ah_there_it_is.storage import create_backup, sqlite_path_from_url, validate_database


class RollbackError(RuntimeError):
    pass


def _fsync_file(path: Path) -> None:
    with path.open("rb") as file:
        os.fsync(file.fileno())


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _state(database: Path) -> dict[str, tuple[int, int, int]]:
    result = {}
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            stat = path.stat()
            result[path.name] = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
    return result


def _remove_empty_sidecars(database: Path) -> None:
    wal = Path(f"{database}-wal")
    shm = Path(f"{database}-shm")
    if wal.exists() and wal.stat().st_size:
        raise RollbackError(f"nonempty WAL prevents standalone rollback file: {wal}")
    wal.unlink(missing_ok=True)
    shm.unlink(missing_ok=True)
    _fsync_dir(database.parent)


def _old_package_validator(python: Path, expected_revision: str) -> Callable[[Path], None]:
    def validate(path: Path) -> None:
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("AH_THERE_IT_IS_")
        }
        environment["AH_THERE_IT_IS_ENV"] = "development"
        environment["AH_THERE_IT_IS_DATABASE_URL"] = f"sqlite:///{path}"
        result = subprocess.run(
            [str(python), "-m", "ah_there_it_is.storage_cli", "validate", str(path)],
            env=environment, capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise RollbackError(
                f"old package rejected {path}: exit={result.returncode}; "
                f"{result.stderr.strip()[:300]}"
            )
        try:
            report = json.loads(result.stdout)
        except ValueError as exc:
            raise RollbackError("old package validation returned invalid JSON") from exc
        if report.get("alembic_revision") != expected_revision:
            raise RollbackError("old package validation returned unexpected revision")
        if report.get("integrity_check") != ["ok"] or report.get("foreign_key_violations"):
            raise RollbackError("old package validation did not confirm database integrity")
    return validate


def _require_units_stopped() -> None:
    for unit in ("ah-there-it-is-web.service", "ah-there-it-is-telegram.service"):
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, "-p", "MainPID", "-p", "ActiveState"],
            check=True, capture_output=True, text=True,
        )
        state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if state.get("MainPID") != "0" or state.get("ActiveState") not in ("inactive", "failed"):
            raise RollbackError(f"stop {unit} before cross-schema rollback")


def rollback_cross_schema(
    database_url: str,
    candidate: Path,
    *,
    expected_old_revision: str,
    validate_old: Callable[[Path], None],
    safety_backup: Path,
    require_stopped: Callable[[], None] = _require_units_stopped,
) -> dict[str, str]:
    active = sqlite_path_from_url(database_url)
    candidate = candidate.expanduser().resolve()
    safety_backup = safety_backup.expanduser().resolve()
    if not active.is_file() or not candidate.is_file():
        raise RollbackError("active database and pre-upgrade backup must exist")
    if len({active, candidate, safety_backup}) != 3:
        raise RollbackError("active, candidate and safety backup paths must differ")
    candidate_wal = Path(f"{candidate}-wal")
    if candidate_wal.exists() and candidate_wal.stat().st_size:
        raise RollbackError("pre-upgrade backup must not depend on a nonempty WAL")
    require_stopped()
    validate_old(candidate)
    if candidate_wal.exists() and candidate_wal.stat().st_size:
        raise RollbackError("pre-upgrade backup changed during old-package validation")
    validate_database(active)  # The upgraded active DB must match this package.

    with sqlite3.connect(active) as connection:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint is None or checkpoint[0] != 0:
            raise RollbackError("active database WAL checkpoint is busy")
    validate_database(active)
    created_safety = create_backup(database_url, safety_backup, overwrite=False)
    validate_database(safety_backup)
    state = _state(active)

    staged = active.with_name(f".{active.name}.old-schema-{uuid4().hex}.tmp")
    quarantine = active.with_name(f"{active.name}.upgraded-{uuid4().hex}")
    original_inode = state[active.name][0]
    published = False
    moved = False
    try:
        with staged.open("xb") as output, candidate.open("rb") as source:
            os.fchmod(output.fileno(), 0o600)
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        validate_old(staged)
        _remove_empty_sidecars(staged)
        require_stopped()
        if _state(active) != state:
            raise RollbackError("active database changed during rollback preparation")
        quarantine.mkdir(mode=0o700)
        moved = True
        for path in (Path(f"{active}-wal"), Path(f"{active}-shm"), active):
            if path.exists():
                os.replace(path, quarantine / path.name)
        _fsync_dir(quarantine)
        _fsync_dir(active.parent)
        os.link(staged, active)  # Fails if another writer recreated the active path.
        published = True
        _fsync_file(active)
        _fsync_dir(active.parent)
        validate_old(active)
        require_stopped()
        _remove_empty_sidecars(active)
        return {
            "restored": str(active),
            "old_revision": expected_old_revision,
            "upgraded_quarantine": str(quarantine),
            "upgraded_safety_backup": created_safety.path,
        }
    except Exception:
        if moved:
            if published and active.exists() and active.stat().st_ino == staged.stat().st_ino:
                active.unlink()
            if not active.exists() and (quarantine / active.name).exists():
                os.link(quarantine / active.name, active)
            if active.exists() and active.stat().st_ino == original_inode:
                for path in (Path(f"{active}-wal"), Path(f"{active}-shm")):
                    saved = quarantine / path.name
                    if saved.exists() and not path.exists():
                        os.link(saved, path)
                _fsync_file(active)
                _fsync_dir(active.parent)
                validate_database(active)
        raise
    finally:
        staged.unlink(missing_ok=True)
        Path(f"{staged}-wal").unlink(missing_ok=True)
        Path(f"{staged}-shm").unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("active_database", type=Path)
    parser.add_argument("pre_upgrade_backup", type=Path)
    parser.add_argument("old_package_python", type=Path)
    parser.add_argument("--old-revision", required=True)
    parser.add_argument("--safety-backup", type=Path)
    args = parser.parse_args()
    safety_backup = args.safety_backup or (
        args.active_database.resolve().parent / "backups"
        / f"pre-rollback-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}.db"
    )
    try:
        result = rollback_cross_schema(
            f"sqlite:///{args.active_database.resolve()}",
            args.pre_upgrade_backup,
            expected_old_revision=args.old_revision,
            validate_old=_old_package_validator(args.old_package_python, args.old_revision),
            safety_backup=safety_backup,
        )
    except Exception as exc:
        print(f"error: cross-schema rollback failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
