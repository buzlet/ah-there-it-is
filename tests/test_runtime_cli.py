from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ah_there_it_is.config import Settings
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.runtime_cli import (
    RuntimeSchemaError,
    build_parser,
    main,
    runtime_schema_gate,
)


def _migrate(database: Path) -> str:
    url = f"sqlite:///{database}"
    upgrade_database(url)
    return url


def test_serve_parser_defaults_to_loopback_and_8000() -> None:
    args = build_parser().parse_args(["serve"])

    assert args.command == "serve"
    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_serve_parser_accepts_explicit_host_and_port() -> None:
    args = build_parser().parse_args(
        ["serve", "--host", "0.0.0.0", "--port", "8123"]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 8123


@pytest.mark.parametrize(
    "argv",
    [
        ["serve", "--host", " "],
        ["serve", "--host", "bad host"],
        ["serve", "--port", "0"],
        ["serve", "--port", "65536"],
        ["serve", "--port", "not-a-port"],
    ],
)
def test_serve_parser_rejects_invalid_host_or_port(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(argv)

    assert exc.value.code == 2


def test_runtime_gate_accepts_current_database_without_mutation(tmp_path: Path) -> None:
    database = tmp_path / "current.db"
    url = _migrate(database)
    before = database.read_bytes()

    status = runtime_schema_gate(url)

    assert status.database_path == str(database.resolve())
    assert status.database_heads == status.packaged_heads
    assert len(status.packaged_heads) == 1
    assert database.read_bytes() == before


def test_runtime_gate_rejects_missing_database_without_creating_it(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.db"

    with pytest.raises(RuntimeSchemaError, match="does not exist"):
        runtime_schema_gate(f"sqlite:///{database}")

    assert not database.exists()


def test_runtime_gate_rejects_uninitialized_database_without_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "uninitialized.db"
    sqlite3.connect(database).close()
    before = database.read_bytes()

    with pytest.raises(RuntimeSchemaError, match="no readable Alembic revision state"):
        runtime_schema_gate(f"sqlite:///{database}")

    assert database.read_bytes() == before


@pytest.mark.parametrize("revision", ["c4cfe3a3e921", "future-revision"])
def test_runtime_gate_rejects_nonmatching_revision_without_mutation(
    tmp_path: Path,
    revision: str,
) -> None:
    database = tmp_path / "mismatch.db"
    url = _migrate(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()
    finally:
        connection.close()
    before = database.read_bytes()

    with pytest.raises(RuntimeSchemaError, match="does not match"):
        runtime_schema_gate(url)

    assert database.read_bytes() == before


def test_serve_runs_uvicorn_factory_only_after_schema_gate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from ah_there_it_is import runtime_cli

    database = tmp_path / "serve.db"
    url = _migrate(database)
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(runtime_cli, "get_settings", lambda: Settings(database_url=url))
    monkeypatch.setattr(
        runtime_cli.uvicorn,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert main(["serve", "--host", "127.0.0.1", "--port", "8124"]) == 0
    assert calls == [
        (
            ("ah_there_it_is.app:create_app",),
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 8124,
                "reload": False,
            },
        )
    ]


def test_serve_missing_database_returns_error_before_uvicorn(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from ah_there_it_is import runtime_cli

    database = tmp_path / "missing.db"
    calls = 0

    def forbidden_run(*args, **kwargs):
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        runtime_cli,
        "get_settings",
        lambda: Settings(database_url=f"sqlite:///{database}"),
    )
    monkeypatch.setattr(runtime_cli.uvicorn, "run", forbidden_run)

    assert main(["serve"]) == 2
    error = capsys.readouterr().err
    assert "does not exist" in error
    assert "python -m ah_there_it_is.storage_cli upgrade" in error
    assert calls == 0
    assert not database.exists()


def test_importing_app_module_does_not_create_default_database(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    database = tmp_path / "ah_there_it_is.db"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    env.pop("AH_THERE_IT_IS_DATABASE_URL", None)

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import ah_there_it_is.app as module; "
                "assert not hasattr(module, 'app'); "
                "assert callable(module.create_app)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not database.exists()
