"""Direct host acceptance for Telegram systemd readiness and failure status.

Uses only scratch SQLite databases, synthetic tokens and local fake Bot APIs.
Run from the repository checkout with `.venv/bin/python`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time

from ah_there_it_is.db.migrations import upgrade_database


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args], capture_output=True, text=True,
        timeout=10,
    )


def _properties(unit: str) -> dict[str, str]:
    result = _systemctl(
        "show", unit, "-p", "ActiveState", "-p", "SubState", "-p",
        "MainPID", "-p", "NRestarts", "-p", "ExecMainStatus",
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def _case(name: str, number: int, root: Path) -> None:
    token = f"synthetic-probe-token-{number}"
    database = root / name / "inventory.db"
    database.parent.mkdir(mode=0o700)
    url = f"sqlite:///{database}"
    upgrade_database(url)
    requests = 0

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            nonlocal requests
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            requests += 1
            if name == "transport" and requests <= 3:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            status = (
                401 if name == "401" else 409 if name == "409" else
                429 if name == "429" and requests <= 2 else
                500 if name == "500" and requests <= 2 else 200
            )
            body = (
                {"ok": True, "result": []} if status == 200
                else {"ok": False, "error_code": status,
                      "description": f"synthetic failure {token}"}
            )
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except BrokenPipeError:
                pass
            time.sleep(0.02)

        def log_message(self, *_args: object) -> None:
            # Bot API URLs include a token in the path.
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        environment = database.parent / "runtime.env"
        environment.write_text("\n".join((
            "AH_THERE_IT_IS_ENV=production",
            f"AH_THERE_IT_IS_DATABASE_URL={url}",
            f"AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN={token}",
            "AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID=7",
            f"AH_THERE_IT_IS_TELEGRAM_BASE_URL=http://127.0.0.1:{server.server_port}",
        )) + "\n", encoding="utf-8")
        environment.chmod(0o600)
        unit = f"ah-telegram-status-{os.getpid()}-{name}.service"
        executable = Path.cwd() / ".venv/bin/ah-there-it-is"
        started = subprocess.run([
            "systemd-run", "--user", "--no-block", f"--unit={unit}",
            "--property=Type=notify", "--property=NotifyAccess=main",
            "--property=TimeoutStartSec=infinity", "--property=Restart=on-failure",
            "--property=RestartPreventExitStatus=2",
            f"--property=EnvironmentFile={environment}",
            str(executable), "telegram-bot", "--poll-timeout", "0",
        ], capture_output=True, text=True, timeout=10)
        if started.returncode:
            raise RuntimeError(f"systemd probe unit start failed: {started.stderr.strip()}")
        try:
            expected = "failed" if name in {"401", "409"} else "active"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = _properties(unit)
                if state.get("ActiveState") == expected:
                    break
                time.sleep(0.2)
            if state.get("ActiveState") != expected:
                raise AssertionError(f"{name}: expected {expected}, got {state}")
            journal = subprocess.run(
                ["journalctl", "--user", "-u", unit, "--no-pager", "-n", "40"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            if name in {"401", "409"}:
                assert state["NRestarts"] == "0", (state, journal.replace(token, "[redacted]"))
                assert state["ExecMainStatus"] == "2", (state, journal.replace(token, "[redacted]"))
            else:
                assert state["SubState"] == "running", state
                assert int(state["MainPID"]) > 0, state
            assert token not in journal
            print(f"{name}: state={expected}, calls={requests}, token_redacted=yes")
        finally:
            _systemctl("stop", unit)
            _systemctl("reset-failed", unit)
            server.shutdown()
            thread.join(timeout=3)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="telegram-systemd-probe-", dir=Path.cwd()) as scratch:
        root = Path(scratch)
        for number, name in enumerate(("401", "409", "429", "500", "transport"), 1):
            _case(name, number, root)


if __name__ == "__main__":
    main()
