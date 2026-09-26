"""Bot identity ownership and operational Telegram failure classification."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from threading import Event

import httpx
import pytest

from ah_there_it_is.config import Settings
from ah_there_it_is.telegram.client import (
    TelegramApiError,
    TelegramBotClient,
    TelegramConflictError,
    TelegramPermanentError,
    TelegramTransportError,
)
from ah_there_it_is.telegram.runtime import TelegramRuntime
from ah_there_it_is.telegram.singleton import (
    TelegramSingletonError, bot_lock_path, telegram_singleton,
)


def _holder(database_url: str, token: str, lock_dir: Path) -> subprocess.Popen[str]:
    script = """
import os, sys
from pathlib import Path
from ah_there_it_is.telegram.singleton import telegram_singleton
with telegram_singleton(sys.argv[1], os.environ['PROBE_BOT_TOKEN'], lock_dir=Path(sys.argv[2])):
    print('ready', flush=True)
    sys.stdin.readline()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, database_url, str(lock_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PROBE_BOT_TOKEN": token},
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "ready"
    return child


@pytest.mark.extended
def test_bot_and_database_ownership_are_independent_and_clean_exit_releases(
    tmp_path: Path,
) -> None:
    first_db = f"sqlite:///{tmp_path / 'first.db'}"
    second_db = f"sqlite:///{tmp_path / 'second.db'}"
    lock_dir = tmp_path / "locks"
    token = "synthetic-secret-bot-token"
    child = _holder(first_db, token, lock_dir)
    try:
        for url, identity in ((first_db, token), (second_db, token),
                              (first_db, "another-bot-token")):
            with pytest.raises(TelegramSingletonError) as error:
                with telegram_singleton(url, identity, lock_dir=lock_dir):
                    pytest.fail("second poller acquired ownership")
            assert token not in str(error.value)
        with telegram_singleton(second_db, "another-bot-token", lock_dir=lock_dir):
            pass
        assert all(token not in path.name for path in lock_dir.iterdir())
        assert lock_dir.stat().st_mode & 0o777 == 0o700
    finally:
        assert child.stdin is not None
        child.stdin.write("stop\n")
        child.stdin.flush()
        child.communicate(timeout=5)
    with telegram_singleton(first_db, token, lock_dir=lock_dir):
        pass


@pytest.mark.extended
def test_sigkill_releases_bot_and_database_ownership(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'inventory.db'}"
    lock_dir = tmp_path / "locks"
    token = "synthetic-secret-bot-token"
    child = _holder(url, token, lock_dir)
    child.send_signal(signal.SIGKILL)
    child.communicate(timeout=5)
    assert child.returncode == -signal.SIGKILL
    with telegram_singleton(url, token, lock_dir=lock_dir):
        pass


def test_invalid_bot_identity_does_not_escape_into_error(tmp_path: Path) -> None:
    invalid = "secret\ud800token"
    with pytest.raises(TelegramSingletonError) as error:
        bot_lock_path(invalid, lock_dir=tmp_path)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, TelegramPermanentError),
        (409, TelegramConflictError),
        (429, TelegramApiError),
        (500, TelegramApiError),
    ],
)
def test_http_status_classification_and_token_redaction(
    status: int, expected: type[Exception]
) -> None:
    token = "synthetic-secret-bot-token"
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={
            "ok": False, "error_code": status,
            "description": f"failure for {token}",
        })
    with TelegramBotClient(
        token, transport=httpx.MockTransport(respond), max_retries=0,
    ) as client:
        with pytest.raises(expected) as error:
            client.get_updates(timeout=0)
    assert token not in str(error.value)
    if status in {429, 500}:
        assert not isinstance(error.value, TelegramPermanentError)


def test_ok_false_permanent_code_redacts_token() -> None:
    token = "synthetic-secret-bot-token"
    with TelegramBotClient(
        token,
        transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, json={"ok": False, "error_code": 401,
                       "description": f"bad {token}"},
        )),
        max_retries=0,
    ) as client:
        with pytest.raises(TelegramPermanentError) as error:
            client.get_updates(timeout=0)
    assert token not in str(error.value)


def test_persistent_conflict_fails_after_bounded_retry(tmp_path: Path) -> None:
    class Polling:
        calls = 0
        def run_once(self):
            self.calls += 1
            raise TelegramConflictError("Telegram HTTP error status=409")
    polling = Polling()
    runtime = TelegramRuntime(
        settings=Settings(telegram_retry_backoff_seconds=0),
        session=object(), client=object(), polling=polling, sleep=lambda _delay: None,
    )
    with pytest.raises(TelegramPermanentError, match="409"):
        runtime.run_forever()
    assert polling.calls == 3


def test_transient_http_and_transport_errors_retry_then_signal_ready(
    tmp_path: Path, monkeypatch
) -> None:
    socket_path = tmp_path / "notify.sock"
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(str(socket_path))
    receiver.settimeout(2)
    monkeypatch.setenv("NOTIFY_SOCKET", str(socket_path))
    stop = Event()
    class Polling:
        calls = 0
        def run_once(self):
            self.calls += 1
            if self.calls == 1:
                raise TelegramApiError("rate limited", status_code=429)
            if self.calls == 2:
                raise TelegramApiError("server error", status_code=500)
            if self.calls == 3:
                raise TelegramTransportError("network timeout")
            stop.set()
    polling = Polling()
    runtime = TelegramRuntime(
        settings=Settings(telegram_retry_backoff_seconds=0),
        session=object(), client=object(), polling=polling, sleep=lambda _delay: None,
    )
    try:
        runtime.run_forever(stop_event=stop)
        assert polling.calls == 4
        assert receiver.recv(32) == b"READY=1"
    finally:
        receiver.close()
