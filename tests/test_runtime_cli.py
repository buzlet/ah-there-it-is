from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from ah_there_it_is.config import Settings, get_settings
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


def test_serve_parser_accepts_nonlocal_opt_in() -> None:
    args = build_parser().parse_args(["serve", "--allow-nonlocal"])

    assert args.allow_nonlocal is True


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.255.12.34", True),
        ("::1", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.50", False),
        ("8.8.8.8", False),
        ("2001:4860:4860::8888", False),
        ("inventory.local", False),
    ],
)
def test_serve_loopback_host_classification(host: str, expected: bool) -> None:
    from ah_there_it_is.runtime_cli import _is_loopback_host

    assert _is_loopback_host(host) is expected


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
        # Stabilize the main file before comparing its bytes: migration uses WAL.
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
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


def test_serve_rejects_nonlocal_before_schema_gate_and_uvicorn(
    monkeypatch,
    capsys,
) -> None:
    from ah_there_it_is import runtime_cli

    monkeypatch.setattr(
        runtime_cli,
        "get_settings",
        lambda: Settings(database_url="sqlite:///unused.db"),
    )
    monkeypatch.setattr(
        runtime_cli,
        "runtime_schema_gate",
        lambda _url: pytest.fail("schema gate must follow the nonlocal guard"),
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        runtime_cli.uvicorn,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    assert main(["serve", "--host", "0.0.0.0"]) == 2
    error = capsys.readouterr().err
    assert "non-loopback" in error
    assert "--allow-nonlocal" in error
    assert "no authentication" in error
    assert calls == []


def test_serve_nonlocal_opt_in_warns_and_passes_requested_host(
    tmp_path: Path,
    monkeypatch,
    capsys,
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

    assert main(
        [
            "serve",
            "--host",
            "192.168.1.50",
            "--port",
            "8124",
            "--allow-nonlocal",
        ]
    ) == 0
    warning = capsys.readouterr().err
    assert "warning:" in warning
    assert "no authentication" in warning
    assert "exposed beyond loopback" in warning
    assert calls == [
        (
            ("ah_there_it_is.app:create_app",),
            {
                "factory": True,
                "host": "192.168.1.50",
                "port": 8124,
                "reload": False,
            },
        )
    ]


def test_serve_nonlocal_opt_in_is_harmless_for_loopback(
    tmp_path: Path,
    monkeypatch,
    capsys,
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

    assert main(["serve", "--host", "LOCALHOST", "--allow-nonlocal"]) == 0
    assert capsys.readouterr().err == ""
    assert calls[0][1]["host"] == "LOCALHOST"


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
    data_dir = tmp_path / "data-home"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    env["AH_THERE_IT_IS_DATA_DIR"] = str(data_dir)
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
    assert not data_dir.exists()



def test_paths_reports_default_database_read_only(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_dir = tmp_path / "not-created"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AH_THERE_IT_IS_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        assert main(["paths"]) == 0
        payload = json.loads(capsys.readouterr().out)
    finally:
        get_settings.cache_clear()

    assert payload == {
        "data_dir": str(data_dir.resolve()),
        "database": {
            "source": "default",
            "path": str((data_dir / "inventory.db").resolve()),
        },
    }
    assert not data_dir.exists()


def test_paths_reports_explicit_file_sqlite_without_rewriting_it(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_dir = tmp_path / "unused-data"
    database = tmp_path / "custom" / "inventory.db"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", f"sqlite:///{database}")
    get_settings.cache_clear()
    try:
        assert main(["paths"]) == 0
        payload = json.loads(capsys.readouterr().out)
    finally:
        get_settings.cache_clear()

    assert payload == {
        "data_dir": str(data_dir.resolve()),
        "database": {
            "source": "explicit",
            "path": str(database.resolve()),
        },
    }
    assert not data_dir.exists()
    assert not database.exists()


def test_paths_does_not_echo_explicit_non_sqlite_credentials(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_dir = tmp_path / "not-created"
    secret_url = "postgresql://user:super-secret@example.invalid/inventory"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", secret_url)
    get_settings.cache_clear()
    try:
        assert main(["paths"]) == 0
        output = capsys.readouterr().out
        payload = json.loads(output)
    finally:
        get_settings.cache_clear()

    assert payload == {
        "data_dir": str(data_dir.resolve()),
        "database": {"source": "explicit", "path": None},
    }
    assert "super-secret" not in output
    assert "postgresql" not in output
    assert not data_dir.exists()


def test_default_serve_gate_does_not_create_data_home(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    data_dir = tmp_path / "missing-data"
    monkeypatch.setenv("AH_THERE_IT_IS_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AH_THERE_IT_IS_DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        assert main(["serve"]) == 2
        error = capsys.readouterr().err
    finally:
        get_settings.cache_clear()

    assert "does not exist" in error
    assert not data_dir.exists()
