"""Direct host probe: switch two disposable releases and delete the old one."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = Path.home() / "apps/ah-there-it-is"
CURRENT = APP_ROOT / "current"
WEB = "ah-there-it-is-web.service"
TELEGRAM = "ah-there-it-is-telegram.service"


def _run(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True,
                          timeout=90).stdout.strip()


def _show(unit: str, property_name: str) -> str:
    return _run("systemctl", "--user", "show", unit, f"-p{property_name}").split("=", 1)[1]


def _health() -> None:
    deadline = time.monotonic() + 12
    while True:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=2) as response:
                assert response.status == 200
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)


def _prepare(source: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for name in ("src", "deploy", ".venv"):
        shutil.copytree(source / name, destination / name, symlinks=True)
    for name in ("pyproject.toml", "README.md"):
        shutil.copyfile(source / name, destination / name)
    _run(str(destination / ".venv/bin/python"), "-m", "pip", "install",
         "--no-deps", "-e", str(destination), cwd=destination)
    assert str(destination) in (destination / ".venv/bin/ah-there-it-is").read_text().splitlines()[0]


def _activate(release: Path) -> None:
    _run(str(release / ".venv/bin/python"), str(release / "deploy/install_user_units.py"),
         "--switch-release", str(release))
    assert CURRENT.resolve() == release.resolve()
    assert _show(WEB, "NeedDaemonReload") == "no"
    assert _show(WEB, "FragmentPath") == str(Path.home() / ".config/systemd/user" / WEB)


def main() -> None:
    original = CURRENT.resolve()
    if original != ROOT or _show(WEB, "ActiveState") != "active":
        raise RuntimeError("run from the active checkout with healthy web unit")
    if _show(TELEGRAM, "MainPID") != "0":
        raise RuntimeError("Telegram unit must be stopped for release probe")
    with tempfile.TemporaryDirectory(prefix="release-lifecycle-", dir=APP_ROOT) as directory:
        old = Path(directory) / "old"
        new = Path(directory) / "new"
        _prepare(ROOT, old)
        _prepare(ROOT, new)
        try:
            _run("systemctl", "--user", "stop", WEB)
            assert _show(WEB, "MainPID") == "0"
            _activate(old)
            _run("systemctl", "--user", "start", WEB)
            _health()
            old_pid = _show(WEB, "MainPID")
            print(f"old release active: pid={old_pid}, stable unit=yes")

            _run("systemctl", "--user", "stop", WEB)
            assert _show(WEB, "MainPID") == "0"
            _activate(new)
            shutil.rmtree(old)
            assert not old.exists()
            _run("systemctl", "--user", "start", WEB)
            _health()
            new_pid = _show(WEB, "MainPID")
            assert new_pid != old_pid
            print(f"new release active after old deletion: pid={new_pid}, stable unit=yes")
        finally:
            _run("systemctl", "--user", "stop", WEB)
            _run(str(ROOT / ".venv/bin/python"), str(ROOT / "deploy/install_user_units.py"),
                 "--switch-release", str(original))
            _run("systemctl", "--user", "start", WEB)
            _health()
            print("original release restored: web health=ok")


if __name__ == "__main__":
    main()
