from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


def test_wheel_contains_and_runs_packaged_migrations(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    wheelhouse = tmp_path / "wheelhouse"
    install_dir = tmp_path / "install"
    outside = tmp_path / "outside"
    fixture = tmp_path / "inventory-portable-v1.json"
    wheelhouse.mkdir()
    outside.mkdir()
    shutil.copy2(repo / "tests/fixtures/inventory-portable-v1.json", fixture)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(repo),
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("ah_there_it_is-*.whl"))

    prefix = "ah_there_it_is/db/migrations/"
    source_versions = {
        path.name
        for path in (repo / "src/ah_there_it_is/db/migrations/versions").glob("*.py")
        if path.name != "__init__.py"
    }
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert prefix + "env.py" in names
    assert prefix + "script.py.mako" in names
    assert {
        prefix + "versions/" + filename for filename in source_versions
    } <= names

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(install_dir),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    smoke = r'''
import json
from importlib.resources import files
from pathlib import Path
import sys

import ah_there_it_is
from sqlalchemy.orm import Session

from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.session import create_db_engine
from ah_there_it_is.services.search import SearchService
from ah_there_it_is.storage import (
    CURRENT_SCHEMA_REVISION,
    import_portable_inventory,
    validate_database,
)

repo = Path(sys.argv[1]).resolve()
outside = Path(sys.argv[2]).resolve()
fixture = Path(sys.argv[3]).resolve()
package_path = Path(ah_there_it_is.__file__).resolve()
resource_path = Path(str(files("ah_there_it_is.db.migrations"))).resolve()
assert not package_path.is_relative_to(repo), package_path
assert not resource_path.is_relative_to(repo), resource_path

fresh = outside / "fresh.db"
fresh_url = f"sqlite:///{fresh}"
upgrade_database(fresh_url)
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

print(json.dumps({
    "package_path": str(package_path),
    "resource_path": str(resource_path),
    "revision": CURRENT_SCHEMA_REVISION,
}))
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(install_dir)
    completed = subprocess.run(
        [sys.executable, "-c", smoke, str(repo), str(outside), str(fixture)],
        cwd=outside,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = completed.stdout.strip().splitlines()[-1]
    assert '"revision": "a31d7f4e9c20"' in payload
