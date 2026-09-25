# test_wheel_migrations.py
from __future__ import annotations

import importlib.util
import json
import os
import signal
from pathlib import Path
import sysconfig
import venv
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import zipfile

from ah_there_it_is.storage import CURRENT_SCHEMA_REVISION


def test_quantity_removed_migration_is_packaged_in_wheel(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(repo),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("ah_there_it_is-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert (
            "ah_there_it_is/db/migrations/versions/"
            "6f2b1c9d4e80_add_quantity_removed_truth.py"
        ) in archive.namelist()


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
    runtime_venv = tmp_path / "runtime-venv"
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
        item_detail_template = archive.read(
            "ah_there_it_is/web/templates/item_detail.html"
        ).decode("utf-8")
        activity_template = archive.read(
            "ah_there_it_is/web/templates/activity.html"
        ).decode("utf-8")
        activity_detail_template = archive.read(
            "ah_there_it_is/web/templates/activity_detail.html"
        ).decode("utf-8")
        item_template = archive.read(
            "ah_there_it_is/web/templates/items.html"
        ).decode("utf-8")
        item_form_template = archive.read(
            "ah_there_it_is/web/templates/_item_form.html"
        ).decode("utf-8")
        item_script = archive.read(
            "ah_there_it_is/web/static/item.js"
        ).decode("utf-8")

    assert migration_prefix + "env.py" in names
    assert migration_prefix + "script.py.mako" in names
    assert {
        migration_prefix + "versions/" + filename for filename in source_versions
    } <= names
    assert "ah_there_it_is/web/templates/item_new.html" in names
    assert "ah_there_it_is/web/templates/item_detail.html" in names
    assert "ah_there_it_is/web/templates/activity.html" in names
    assert "ah_there_it_is/web/templates/activity_detail.html" in names
    assert "/activity" in activity_template
    assert "event.from_path.label" in activity_detail_template
    assert "Historical Category paths" in activity_detail_template
    assert "Next history page" in item_detail_template
    assert "ah_there_it_is/web/templates/tree_edit.html" in names
    assert "ah_there_it_is/web/templates/tree_detail.html" in names
    assert "ah_there_it_is/web/templates/_item_form.html" in names
    assert "ah_there_it_is/web/static/tree.js" in names
    assert "ah_there_it_is/web/static/item.js" in names
    assert "Condition/state unknown" in item_form_template
    assert "Condition / state" in item_template
    assert "Location status" in item_template
    assert "Location unknown" in item_template
    assert 'data-transition-kind="reactivate"' in item_detail_template
    assert "location_mode" in item_detail_template
    assert 'data-transition-kind="location-unknown"' in item_detail_template
    assert "reactivate" in item_script
    assert "[console_scripts]" in entry_points
    assert "ah-there-it-is = ah_there_it_is.runtime_cli:main" in entry_points

    venv.EnvBuilder(with_pip=True).create(runtime_venv)
    scripts = runtime_venv / ("Scripts" if os.name == "nt" else "bin")
    runtime_python = scripts / ("python.exe" if os.name == "nt" else "python")
    console_script = scripts / ("ah-there-it-is.exe" if os.name == "nt" else "ah-there-it-is")
    assert runtime_python.is_file()
    install_env = os.environ.copy()
    install_env.pop("PYTHONPATH", None)
    subprocess.run(
        [str(runtime_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)],
        env=install_env,
        check=True,
        capture_output=True,
        text=True,
    )
    site_packages = Path(subprocess.run(
        [str(runtime_python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    # Reuse already installed test dependencies without fetching from a network.
    (site_packages / "parent-dependencies.pth").write_text(
        str(Path(sysconfig.get_paths()["purelib"]).resolve()) + "\n", encoding="utf-8"
    )
    assert console_script.is_file()

    runtime_env = os.environ.copy()
    runtime_env.pop("PYTHONPATH", None)
    runtime_env["PYTHONNOUSERSITE"] = "1"
    runtime_env["PATH"] = str(scripts) + os.pathsep + runtime_env.get("PATH", "")
    runtime_env["AH_THERE_IT_IS_LLM_PROVIDER"] = "heuristic"
    runtime_env.pop("AH_THERE_IT_IS_DATABASE_URL", None)
    runtime_env.pop("AH_THERE_IT_IS_DATA_DIR", None)
    (outside / "home").mkdir()
    runtime_env["HOME"] = str(outside / "home")
    runtime_env["USERPROFILE"] = str(outside / "home")
    runtime_env["XDG_DATA_HOME"] = str(outside / "xdg-data")
    runtime_env["LOCALAPPDATA"] = str(outside / "local-app-data")

    installed_probe = subprocess.run(
        [
            str(runtime_python),
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
    assert package_path.is_relative_to(runtime_venv), package_path
    assert resource_path.is_relative_to(runtime_venv), resource_path
    installed_schema = subprocess.run(
        [
            str(runtime_python), "-c",
            "from ah_there_it_is.agent.schemas import ItemIdInput, LocationIdInput; "
            "assert ItemIdInput.model_fields['page_size'].default == 50; "
            "assert LocationIdInput.model_fields['page_size'].default == 50; "
            "assert ItemIdInput.model_json_schema()['properties']['page_size']['maximum'] == 100; "
            "assert LocationIdInput.model_json_schema()['properties']['page']['minimum'] == 1",
        ],
        cwd=outside, env=runtime_env, check=True, capture_output=True, text=True,
    )
    assert installed_schema.returncode == 0

    upgrade_cwd = outside / "upgrade-cwd"
    serve_cwd = outside / "serve-cwd"
    upgrade_cwd.mkdir()
    serve_cwd.mkdir()
    data_dir = (
        outside / "local-app-data" / "AhThereItIs"
        if os.name == "nt" else outside / "xdg-data" / "ah-there-it-is"
    )
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
            str(runtime_python),
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

    rehearsal_candidate = outside / "installed-rehearsal-candidate.db"
    subprocess.run(
        [str(runtime_python), "-m", "ah_there_it_is.storage_cli", "backup", str(rehearsal_candidate)],
        cwd=outside, env=runtime_env, check=True, capture_output=True, text=True,
    )
    active_before_rehearsal = fresh.read_bytes()
    installed_rehearsal = subprocess.run(
        [str(runtime_python), "-m", "ah_there_it_is.storage_cli", "restore-rehearsal", str(rehearsal_candidate)],
        cwd=outside, env=runtime_env, check=True, capture_output=True, text=True,
    )
    rehearsal_report = json.loads(installed_rehearsal.stdout)
    assert rehearsal_report["ok"] is True
    assert rehearsal_report["restore_mechanics"]["ok"] is True
    assert rehearsal_report["physical_validation"]["ok"] is True
    assert rehearsal_report["doctor"]["ok"] is True
    assert fresh.read_bytes() == active_before_rehearsal

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
            str(runtime_python),
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
    assert f'"revision": "{CURRENT_SCHEMA_REVISION}"' in payload

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

    nonlocal_result = subprocess.run(
        [
            str(console_script),
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            str(_free_local_port()),
        ],
        cwd=outside,
        env=missing_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert nonlocal_result.returncode == 2
    assert (
        "non-loopback serving requires --allow-nonlocal"
        in nonlocal_result.stderr
    )
    assert "configured database does not exist" not in nonlocal_result.stderr
    assert not missing.exists()

    allowed_nonlocal_result = subprocess.run(
        [
            str(console_script),
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            str(_free_local_port()),
            "--allow-nonlocal",
        ],
        cwd=outside,
        env=missing_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert allowed_nonlocal_result.returncode == 2
    assert (
        "warning: application has no authentication"
        in allowed_nonlocal_result.stderr
    )
    assert (
        "configured database does not exist" in allowed_nonlocal_result.stderr
    )
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
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
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
        item_form_status, item_form_body = _http_text(f"http://127.0.0.1:{port}/items/new")
        assert item_form_status == 200
        assert 'name="attributes"' in item_form_body
        category_status, category_body = _http_text(f"http://127.0.0.1:{port}/categories")
        assert category_status == 200
        assert "Add category" in category_body
        items_status, items_body = _http_text(f"http://127.0.0.1:{port}/items?q=absent")
        assert items_status == 200
        assert "Search items" in items_body
        assert "No matching Items for these filters." in items_body
        activity_status, activity_body = _http_text(
            f"http://127.0.0.1:{port}/activity"
        )
        assert activity_status == 200
        assert "Activity" in activity_body
        assert "Total: 0" in activity_body
        tree_asset_status, tree_asset_body = _http_text(f"http://127.0.0.1:{port}/static/tree.js")
        assert tree_asset_status == 200
        assert "data-tree-form" in tree_asset_body
    finally:
        if process.poll() is None:
            process.send_signal(signal.CTRL_C_EVENT if os.name == "nt" else signal.SIGINT)
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
