# verification_paths.py
"""Platform-neutral temporary paths for canonical repository verification."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def migration_check() -> None:
    with tempfile.TemporaryDirectory(prefix="ah-there-it-is-migration-") as temp_dir:
        database = Path(temp_dir) / "inventory.db"
        environment = os.environ.copy()
        environment["AH_THERE_IT_IS_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
        for operation in ("upgrade", "migration-check"):
            subprocess.run(
                [sys.executable, "-m", "ah_there_it_is.storage_cli", operation],
                env=environment,
                check=True,
            )


def main() -> None:
    if sys.argv[1:] != ["migration-check"]:
        raise SystemExit("usage: python -m ah_there_it_is.verification_paths migration-check")
    migration_check()


if __name__ == "__main__":
    main()
