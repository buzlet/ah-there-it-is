"""Direct systemd probe for the production-only preflight used by both shipped units."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess
import tempfile
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / ".venv/bin/ah-there-it-is"


def _preflight(unit_path: Path) -> str:
    values = [line.split("=", 1)[1] for line in unit_path.read_text().splitlines()
              if line.startswith("ExecStartPre=")]
    if len(values) != 1:
        raise RuntimeError(f"expected one startup preflight in {unit_path}")
    command = shlex.split(values[0].replace("%h", str(Path.home())))
    if command[0].endswith("/current/.venv/bin/ah-there-it-is"):
        command[0] = str(ENTRYPOINT)
    if command != [str(ENTRYPOINT), "schema-check", "--require-production"]:
        raise RuntimeError(f"unexpected production preflight in {unit_path}: {command!r}")
    return " ".join(shlex.quote(argument) for argument in command)


def _run(root: Path, case: str, contents: str, *, succeeds: bool) -> None:
    environment = root / f"{case}.env"
    environment.write_text(contents + "AH_THERE_IT_IS_LLM_API_KEY=synthetic-secret-marker\n")
    environment.chmod(0o600)
    marker = root / f"{case}.started"
    command = [
        "systemd-run", "--user", "--wait", "--pipe", "--collect", "-P",
        f"--unit=ah-p2-004-{uuid4().hex}.service",
        "-p", "Type=oneshot",
        "-p", f"WorkingDirectory={root}",
        "-p", f"EnvironmentFile={environment}",
        "-p", f"ExecStartPre={_preflight(ROOT / 'deploy/systemd/ah-there-it-is-web.service')}",
        "/usr/bin/touch", str(marker),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if (result.returncode == 0) is not succeeds:
        raise RuntimeError(f"{case}: unexpected systemd result {result.returncode}: {result.stderr}")
    if marker.exists() is not succeeds:
        raise RuntimeError(f"{case}: production preflight start marker mismatch")
    output = result.stdout + result.stderr
    if "synthetic-secret-marker" in output:
        raise RuntimeError(f"{case}: configuration secret was echoed")
    print(f"{case}: {'started' if succeeds else 'rejected before ExecStart'}, secret redacted")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ah-there-it-is-prod-preflight-") as directory:
        root = Path(directory)
        database = root / "prepared.db"
        # Explicitly prepare the database using the installed migration entrypoint.
        subprocess.run(
            [str(ROOT / ".venv/bin/python"), "-m", "ah_there_it_is.storage_cli", "upgrade"],
            cwd=root,
            env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
                 "PYTHONPATH": str(ROOT / "src"), "AH_THERE_IT_IS_ENV": "production",
                 "AH_THERE_IT_IS_DATABASE_URL": f"sqlite:///{database}"},
            check=True, capture_output=True, text=True,
        )
        relative = "AH_THERE_IT_IS_DATABASE_URL=sqlite:///prepared.db\n"
        absolute = f"AH_THERE_IT_IS_DATABASE_URL=sqlite:///{database}\n"
        units = (ROOT / "deploy/systemd/ah-there-it-is-web.service",
                 ROOT / "deploy/systemd/ah-there-it-is-telegram.service")
        if _preflight(units[0]) != _preflight(units[1]):
            raise RuntimeError("web and Telegram services use different startup preflights")
        _run(root, "unset-mode", relative, succeeds=False)
        _run(root, "unset-mode-absolute", absolute, succeeds=False)
        _run(root, "development-mode", "AH_THERE_IT_IS_ENV=development\n" + absolute,
             succeeds=False)
        _run(root, "malformed-mode", "AH_THERE_IT_IS_ENV=Production\n" + absolute,
             succeeds=False)
        _run(root, "missing-database", "AH_THERE_IT_IS_ENV=production\n", succeeds=False)
        _run(root, "relative-production", "AH_THERE_IT_IS_ENV=production\n" + relative,
             succeeds=False)
        _run(root, "valid-production", "AH_THERE_IT_IS_ENV=production\n" + absolute,
             succeeds=True)


if __name__ == "__main__":
    main()
