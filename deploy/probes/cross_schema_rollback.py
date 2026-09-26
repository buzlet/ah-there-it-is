"""Direct scratch rehearsal against the old package at git commit 294e775."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

from ah_there_it_is.storage import validate_database


ROOT = Path(__file__).resolve().parents[2]
OLD_REVISION = "1a7c4e9d2b10"
WEB = "ah-there-it-is-web.service"


def _run(args: list[str], *, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, env=env, cwd=ROOT, text=True, capture_output=True,
                            timeout=90)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {args[:3]!r}: {result.stderr[-500:]}")
    return result.stdout.strip()


def _environment(database: Path) -> dict[str, str]:
    result = {key: value for key, value in os.environ.items()
              if not key.startswith("AH_THERE_IT_IS_")}
    result["AH_THERE_IT_IS_ENV"] = "development"
    result["AH_THERE_IT_IS_DATABASE_URL"] = f"sqlite:///{database}"
    return result


def _old_release(directory: Path) -> Path:
    old = directory / "old-release"
    old.mkdir()
    archived = subprocess.run(["git", "archive", "294e775"], cwd=ROOT,
                              capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archived)) as archive:
        archive.extractall(old, filter="data")
    shutil.copytree(ROOT / ".venv", old / ".venv", symlinks=True)
    _run([str(old / ".venv/bin/python"), "-m", "pip", "install", "--no-deps",
          "-e", str(old)])
    assert str(old) in (old / ".venv/bin/ah-there-it-is").read_text().splitlines()[0]
    return old


def _health(port: int) -> None:
    deadline = time.monotonic() + 12
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                assert response.status == 200
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cross-schema-rehearsal-") as directory:
        scratch = Path(directory)
        old = _old_release(scratch)
        old_python = old / ".venv/bin/python"
        active = scratch / "active.db"
        candidate = scratch / "pre-upgrade.db"
        old_env = _environment(active)
        _run([str(old_python), "-m", "ah_there_it_is.storage_cli", "upgrade"], env=old_env)
        with sqlite3.connect(active) as connection:
            connection.execute("CREATE TABLE rollback_probe (value TEXT NOT NULL)")
            connection.execute("INSERT INTO rollback_probe VALUES ('old release data')")
        old_backup = json.loads(_run(
            [str(old_python), "-m", "ah_there_it_is.storage_cli", "backup", str(candidate)],
            env=old_env,
        ))
        assert old_backup["alembic_revision"] == OLD_REVISION
        _run([str(old_python), "-m", "ah_there_it_is.storage_cli", "validate", str(candidate)],
             env=old_env)
        current_env = _environment(active)
        _run([sys.executable, "-m", "ah_there_it_is.storage_cli", "upgrade"],
             env=current_env)
        validate_database(active)

        # Leave committed upgraded data in WAL after real process death.
        crash = subprocess.run([sys.executable, "-c", (
            "import os,sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute('CREATE TABLE upgraded_only (value TEXT)'); c.commit(); os._exit(0)"
        ), str(active)], capture_output=True, text=True)
        assert crash.returncode == 0
        assert Path(f"{active}-wal").stat().st_size > 0

        backup_paths = []
        for _ in range(2):
            report = json.loads(_run(
                [sys.executable, "-m", "ah_there_it_is.storage_cli", "backup-auto",
                 str(scratch / "backups")], env=current_env,
            ))
            backup_paths.append(Path(report["path"]))
        assert backup_paths[0] != backup_paths[1]
        assert all(path.is_file() for path in backup_paths)
        print("old package backup validated; upgraded WAL present; repeat backups distinct")

        _run(["systemctl", "--user", "stop", WEB])
        try:
            restored = json.loads(_run([
                sys.executable, str(ROOT / "deploy/cross_schema_rollback.py"),
                str(active), str(candidate), str(old_python),
                "--old-revision", OLD_REVISION,
            ], env=current_env))
            assert not Path(f"{active}-wal").exists()
            assert not Path(f"{active}-shm").exists()
            assert restored["old_revision"] == OLD_REVISION
            validate_database(Path(restored["upgraded_safety_backup"]))
            validate_database(Path(restored["upgraded_quarantine"]) / active.name)
            _run([str(old_python), "-m", "ah_there_it_is.storage_cli", "validate",
                  str(active)], env=old_env)
            with sqlite3.connect(active) as connection:
                assert connection.execute("SELECT value FROM rollback_probe").fetchone()[0] == "old release data"
            old_web = subprocess.Popen(
                [str(old / ".venv/bin/ah-there-it-is"), "serve", "--port", "18792"],
                cwd=old, env=old_env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True,
            )
            try:
                _health(18792)
                assert old_web.poll() is None
            finally:
                old_web.terminate()
                old_web.communicate(timeout=10)
            print("cross-schema rollback: old data, old package validation and old web health=ok; stale sidecars=none")
        finally:
            _run(["systemctl", "--user", "start", WEB])
            _health(8000)
            print("production web restored: health=ok")


if __name__ == "__main__":
    main()
