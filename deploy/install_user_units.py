"""Install stable user units, optionally switch releases, and verify effective systemd state."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
UNIT_NAMES = ("ah-there-it-is-web.service", "ah-there-it-is-telegram.service")
APP_ROOT = Path.home() / "apps/ah-there-it-is"
UNIT_DIR = Path.home() / ".config/systemd/user"


def copy_units(source_dir: Path, unit_dir: Path) -> None:
    """Replace linked or older unit files with standalone copies."""
    unit_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in UNIT_NAMES:
        source = source_dir / name
        contents = source.read_bytes()
        with tempfile.NamedTemporaryFile(dir=unit_dir, prefix=f".{name}.", delete=False) as file:
            temporary = Path(file.name)
            try:
                file.write(contents)
                file.flush()
                os.fsync(file.fileno())
                os.fchmod(file.fileno(), 0o644)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, unit_dir / name)
        finally:
            temporary.unlink(missing_ok=True)


def switch_release(current: Path, release: Path) -> None:
    """Atomically point current to one prepared release directory."""
    if not release.is_absolute() or not release.is_dir():
        raise ValueError("release must be an existing absolute directory")
    if not (release / ".venv/bin/ah-there-it-is").is_file():
        raise ValueError("release has no installed ah-there-it-is entrypoint")
    if current.exists() and not current.is_symlink():
        raise ValueError("current must be a symlink")
    current.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = current.with_name(f"{current.name}.next-{uuid4().hex}")
    try:
        temporary.symlink_to(release, target_is_directory=True)
        os.replace(temporary, current)
    finally:
        temporary.unlink(missing_ok=True)


def _systemctl(*args: str) -> str:
    return subprocess.run(
        ["systemctl", "--user", *args], check=True, text=True, capture_output=True,
    ).stdout.strip()


def _properties(name: str) -> dict[str, str]:
    output = _systemctl(
        "show", name, "-p", "FragmentPath", "-p", "NeedDaemonReload",
        "-p", "MainPID", "-p", "ActiveState", "-p", "EnvironmentFiles",
        "-p", "ExecStart", "-p", "ExecStartPre", "-p", "UnsetEnvironment",
    )
    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = f"{properties[key]}\n{value}" if key in properties else value
    return properties


def require_stopped() -> None:
    for name in UNIT_NAMES:
        state = _properties(name)
        if state.get("MainPID") != "0" or state.get("ActiveState") not in ("inactive", "failed"):
            raise RuntimeError(f"stop {name} before switching release")


def verify_effective_units(unit_dir: Path = UNIT_DIR) -> None:
    for name in UNIT_NAMES:
        path = unit_dir / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"unit must be an installed regular file: {path}")
        state = _properties(name)
        if Path(state.get("FragmentPath", "")) != path or state.get("NeedDaemonReload") != "no":
            raise RuntimeError(f"systemd has not loaded installed unit {name}")
        if "ah-there-it-is schema-check" not in state.get("ExecStartPre", ""):
            raise RuntimeError(f"systemd has an unexpected preflight for {name}")
        if "/current/.venv/bin/ah-there-it-is" not in state.get("ExecStart", ""):
            raise RuntimeError(f"systemd has an unexpected release path for {name}")
        environment = state.get("EnvironmentFiles", "")
        if "runtime.env" not in environment:
            raise RuntimeError(f"systemd has no common environment for {name}")
        if name.endswith("web.service"):
            command = state.get("ExecStart", "")
            unset = state.get("UnsetEnvironment", "")
            if any(value not in command for value in (
                "serve", "--host 0.0.0.0", "--port 8000", "--allow-nonlocal",
            )):
                raise RuntimeError("web unit does not use the reviewed trusted-LAN command")
            if "telegram.env" in environment or any(value not in unset for value in (
                "AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN",
                "AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID",
            )):
                raise RuntimeError("web unit can inherit Telegram credentials")
        elif "telegram.env" not in environment:
            raise RuntimeError("Telegram unit has no isolated secret file")
        print(f"verified {name}: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--switch-release", type=Path)
    args = parser.parse_args()
    release = args.switch_release
    if release is not None:
        if release.resolve() != ROOT:
            parser.error("run this installer from the release being activated")
        require_stopped()
    copy_units(ROOT / "deploy/systemd", UNIT_DIR)
    if release is not None:
        switch_release(APP_ROOT / "current", release)
    _systemctl("daemon-reload")
    verify_effective_units()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
