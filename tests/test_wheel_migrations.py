from __future__ import annotations

import importlib.util
import json
import os
import signal
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import zipfile


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_text(url: str) -> tuple[int, str]:
    with urlopen(url, timeout=1.0) as response:
        return int(response.status), response.read().decode("utf-8")


def test_wheel_contains_and_runs_packaged_migrations_and_runtime(
    tmp_path: Path,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    wheelhouse = tmp_path / "wheelhouse"
    prefix_install = tmp_path / "runtime-prefix"
    outside = tmp_path / "outside"
    fixture = tmp_path / "inventory-portable-v1.json"
    wheelhouse.mkdir()
    outside.mkdir()
    shutil.copy2(repo / "tests/fixtures/inventory-portable-v1.json", fixture)

    build_command = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheelhouse),
        str(repo),
    ]
    # U24 is intentionally provisioned with the build backend toolchain and
    # must exercise the no-build-isolation path. Generic CI only installs the
    # project/test dependencies, so let pip isolate pyproject build requirements
    # there instead of adding wheel/setuptools as application dependencies.
    if (
        importlib.util.find_spec("setuptools") is not None
        and importlib.util.find_spec("wheel") is not None
    ):
        build_command.insert(4, "--no-build-isolation")

    subprocess.run(
        build_command,
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("ah_there_it_is-*.whl"))

    migration_prefix = "ah_there_it_is/db/migrations/"
    source_versions = {
        path.name
        for path in (repo / "src/ah_there_it_is/db/migrations/versions").glob("*.py")
        if path.name != "__init__.py"
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode("utf-8")

    assert migration_prefix + "env.py" in names
    assert migration_prefix + "script.py.mako" in names
    assert {
        migration_prefix + "versions/" + filename for filename in source_versions
    } <= names
    assert "[console_scripts]" in entry_points
    assert "ah-there-it-is = ah_there_it_is.runtime_cli:main" in entry_points

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--ignore-installed",
            "--prefix",
            str(prefix_install),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    installed_init = next(
        prefix_install.glob(
            "lib/python*/site-packages/ah_there_it_is/__init__.py"
        )
    )
    site_packages = installed_init.parents[1]
    console_script = prefix_install / "bin" / "ah-there-it-is"
    assert console_script.is_file()

    runtime_env = os.environ.copy()
    runtime_env["PYTHONPATH"] = str(site_packages)
    runtime_env["AH_THERE_IT_IS_LLM_PROVIDER"] = "heuristic"
    runtime_env.pop("AH_THERE_IT_IS_DATABASE_URL", None)
    runtime_env.pop("AH_THERE_IT_IS_DATA_DIR", None)
    runtime_env["HOME"] = str(outside / "home")
    runtime_env["XDG_DATA_HOME"] = str(outside / "xdg-data")

    installed_probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from importlib.resources import files; "
                "from pathlib import Path; "
                "import ah_there_it_is; "
                "print(Path(ah_there_it_is.__file__).resolve()); "
                "print(Path(str(files('ah_there_it_is.db.migrations'))).resolve())"
            ),
        ],
        cwd=outside,
        env=runtime_env,
        check=True,
        capture_output=True,
        text=True,
    )
    package_path, resource_path = [
        Path(line.strip()).resolve()
        for line in installed_probe.stdout.strip().splitlines()[-2:]
    ]
    assert not package_path.is_relative_to(repo), package_path
    assert not resource_path.is_relative_to(repo), resource_path

    upgrade_cwd = outside / "upgrade-cwd"
    serve_cwd = outside / "serve-cwd"
    upgrade_cwd.mkdir()
    serve_cwd.mkdir()
    data_dir = outside / "xdg-data" / "ah-there-it-is"
    fresh = data_dir / "inventory.db"

    path_payloads = []
    for cwd in (upgrade_cwd, serve_cwd):
        completed_paths = subprocess.run(
            [str(console_script), "paths"],
            cwd=cwd,
            env=runtime_env,
            check=True,
            capture_output=True,
            text=True,
        )
        path_payloads.append(json.loads(completed_paths.stdout))

    expected_paths = {
        "data_dir": str(data_dir.resolve()),
        "database": {
            "source": "default",
            "path": str(fresh.resolve()),
        },
    }
    assert path_payloads == [expected_paths, expected_paths]
    assert not data_dir.exists()
    missing_doctor = subprocess.run(
        [str(console_script), "doctor"],
        cwd=outside,
        env=runtime_env,
        capture_output=True,
        text=True,
    )
    assert missing_doctor.returncode == 2
    assert json.loads(missing_doctor.stdout)["ok"] is False
    assert not data_dir.exists()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "ah_there_it_is.storage_cli",
            "upgrade",
        ],
        cwd=upgrade_cwd,
        env=runtime_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert fresh.is_file()
    healthy_doctor = subprocess.run(
        [str(console_script), "doctor"],
        cwd=serve_cwd,
        env=runtime_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(healthy_doctor.stdout)["ok"] is True

    migration_smoke = r'''
import json
from pathlib import Path
import sys

from sqlalchemy.orm import Session

from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage import (
    CURRENT_SCHEMA_REVISION,
    import_portable_inventory,
    validate_database,
)

outside = Path(sys.argv[1]).resolve()
fixture = Path(sys.argv[2]).resolve()
fresh = Path(sys.argv[3]).resolve()
fresh_url = f"sqlite:///{fresh}"
assert validate_database(fresh).alembic_revision == CURRENT_SCHEMA_REVISION

imported = outside / "imported.db"
result = import_portable_inventory(fresh_url, fixture, imported)
assert result.source_alembic_revision == "c4cfe3a3e921"
assert validate_database(imported).alembic_revision == CURRENT_SCHEMA_REVISION

engine = create_db_engine(f"sqlite:///{imported}")
try:
    with Session(engine) as session:
        assert SearchService(session).search_items("CH341A")[0].id == 1001
finally:
    engine.dispose()

print(json.dumps({"revision": CURRENT_SCHEMA_REVISION}))
'''
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            migration_smoke,
            str(outside),
            str(fixture),
            str(fresh),
        ],
        cwd=outside,
        env=runtime_env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = completed.stdout.strip().splitlines()[-1]
    assert '"revision": "b62f9d8a3c41"' in payload

    missing = outside / "missing.db"
    missing_env = runtime_env.copy()
    missing_env["AH_THERE_IT_IS_DATABASE_URL"] = f"sqlite:///{missing}"
    missing_result = subprocess.run(
        [
            str(console_script),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(_free_local_port()),
        ],
        cwd=outside,
        env=missing_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert missing_result.returncode == 2
    assert "does not exist" in missing_result.stderr
    assert "python -m ah_there_it_is.storage_cli upgrade" in missing_result.stderr
    assert not missing.exists()

    outdated = outside / "outdated.db"
    shutil.copy2(fresh, outdated)
    connection = sqlite3.connect(outdated)
    try:
        connection.execute(
            "UPDATE alembic_version SET version_num = ?",
            ("c4cfe3a3e921",),
        )
        connection.commit()
    finally:
        connection.close()
    outdated_before = outdated.read_bytes()
    outdated_env = runtime_env.copy()
    outdated_env["AH_THERE_IT_IS_DATABASE_URL"] = f"sqlite:///{outdated}"
    outdated_result = subprocess.run(
        [
            str(console_script),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(_free_local_port()),
        ],
        cwd=outside,
        env=outdated_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert outdated_result.returncode == 2
    assert "does not match this installed package" in outdated_result.stderr
    assert outdated.read_bytes() == outdated_before

    port = _free_local_port()
    process = subprocess.Popen(
        [
            str(console_script),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=serve_cwd,
        env=runtime_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        health_payload: dict[str, object] | None = None
        last_error: Exception | None = None
        for _ in range(100):
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    "installed runtime exited before health check: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            try:
                status, body = _http_text(f"http://127.0.0.1:{port}/health")
                assert status == 200
                health_payload = json.loads(body)
                break
            except (URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                time.sleep(0.1)

        assert health_payload is not None, last_error
        assert health_payload["status"] == "ok"
        assert health_payload["llm_provider"] == "heuristic"

        index_status, index_body = _http_text(f"http://127.0.0.1:{port}/")
        assert index_status == 200
        assert "Inventory chat" in index_body
        assert "/static/chat.js" in index_body

        asset_status, asset_body = _http_text(
            f"http://127.0.0.1:{port}/static/style.css"
        )
        assert asset_status == 200
        assert len(asset_body) > 100
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    assert process.returncode == 0

    stray_names = (
        "ah_there_it_is.db",
        "ah_there_it_is.db-wal",
        "ah_there_it_is.db-shm",
        "inventory.db",
        "inventory.db-wal",
        "inventory.db-shm",
    )
    for cwd in (upgrade_cwd, serve_cwd):
        assert all(not (cwd / name).exists() for name in stray_names)
