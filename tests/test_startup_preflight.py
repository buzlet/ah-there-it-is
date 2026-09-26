"""Production configuration and service preflight must fail closed."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ah_there_it_is.config import Settings, resolve_database_url
from ah_there_it_is.db.migrations import upgrade_database


def _run(
    command: list[str], *, mode: str | None, database: Path | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if mode is None:
        env.pop("AH_THERE_IT_IS_ENV", None)
    else:
        env["AH_THERE_IT_IS_ENV"] = mode
    env.pop("AH_THERE_IT_IS_DATABASE_URL", None)
    if database is not None:
        env["AH_THERE_IT_IS_DATABASE_URL"] = f"sqlite:///{database}"
    return subprocess.run(
        [sys.executable, *command],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        cwd=cwd,
    )


@pytest.mark.parametrize(("mode", "command"), [
    ("Production", ["-m", "ah_there_it_is.runtime_cli", "paths"]),
    ("production ", ["-m", "ah_there_it_is.runtime_cli", "serve"]),
    ("prod", ["-m", "ah_there_it_is.runtime_cli", "telegram-bot"]),
    ("unknown", ["-m", "ah_there_it_is.storage_cli", "migration-check"]),
    ("", ["-m", "ah_there_it_is.runtime_cli", "schema-check", "--require-production"]),
])
def test_malformed_environment_rejected_by_real_entrypoints(
    mode: str, command: list[str],
) -> None:
    # Config validation happens before command-specific execution. Pairing every
    # malformed mode with a different real entrypoint preserves both factor
    # coverages without paying for the redundant 5x5 subprocess product.
    result = _run(command, mode=mode)
    assert result.returncode != 0
    assert "configuration" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_environment_validation_preserves_exact_supported_modes(tmp_path: Path) -> None:
    assert resolve_database_url({"AH_THERE_IT_IS_ENV": "development"})
    database = tmp_path / "inventory.db"
    assert resolve_database_url({
        "AH_THERE_IT_IS_ENV": "production",
        "AH_THERE_IT_IS_DATABASE_URL": f"sqlite:///{database}",
    })
    with pytest.raises(ValueError):
        resolve_database_url({"AH_THERE_IT_IS_ENV": "Production"})
    with pytest.raises(ValueError):
        Settings(environment="prod")


def test_production_without_database_fails_without_secret_echo() -> None:
    result = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check"], mode="production",
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "invalid AH_THERE_IT_IS configuration" in result.stderr


def test_production_systemd_preflight_rejects_unset_mode_without_echo() -> None:
    result = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check", "--require-production"],
        mode=None,
    )
    assert result.returncode == 2
    assert "explicit production configuration" in result.stderr
    assert "Traceback" not in result.stderr


def test_unset_mode_rejects_prepared_relative_database(tmp_path: Path) -> None:
    database = tmp_path / "relative.db"
    upgrade_database(f"sqlite:///{database}")
    result = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check", "--require-production"],
        mode=None,
        database=Path("relative.db"),
        cwd=tmp_path,
    )
    assert result.returncode == 2
    assert "explicit production configuration" in result.stderr
    assert "relative.db" not in result.stderr


def test_development_default_is_allowed_outside_production_preflight(
    tmp_path: Path,
) -> None:
    database = tmp_path / "development.db"
    upgrade_database(f"sqlite:///{database}")
    ordinary = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check"],
        mode="development", database=database,
    )
    required = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check", "--require-production"],
        mode="development", database=database,
    )
    assert ordinary.returncode == 0
    assert required.returncode == 2


def test_production_preflight_accepts_absolute_prepared_database(tmp_path: Path) -> None:
    database = tmp_path / "production.db"
    upgrade_database(f"sqlite:///{database}")
    result = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check", "--require-production"],
        mode="production", database=database,
    )
    assert result.returncode == 0


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("state", ["missing", "unversioned", "mismatch"])
def test_service_schema_check_rejects_without_writing_database(
    tmp_path: Path, state: str,
) -> None:
    database = tmp_path / "inventory.db"
    if state == "unversioned":
        sqlite3.connect(database).close()
    elif state == "mismatch":
        upgrade_database(f"sqlite:///{database}")
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE alembic_version SET version_num='old-revision'")
    before = _snapshot(tmp_path)

    result = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check"],
        mode="production", database=database,
    )

    assert result.returncode == 2
    assert _snapshot(tmp_path) == before


def test_service_schema_check_accepts_prepared_database(tmp_path: Path) -> None:
    database = tmp_path / "inventory.db"
    upgrade_database(f"sqlite:///{database}")
    before = _snapshot(tmp_path)

    result = _run(
        ["-m", "ah_there_it_is.runtime_cli", "schema-check"],
        mode="production", database=database,
    )

    assert result.returncode == 0
    assert _snapshot(tmp_path) == before


def test_service_units_use_read_only_preflight() -> None:
    root = Path(__file__).resolve().parents[1]
    for name in ("ah-there-it-is-web.service", "ah-there-it-is-telegram.service"):
        unit = (root / "deploy" / "systemd" / name).read_text()
        preflight = [line for line in unit.splitlines() if line.startswith("ExecStartPre=")]
        assert len(preflight) == 1
        assert preflight[0].endswith(
            "/ah-there-it-is schema-check --require-production"
        )
