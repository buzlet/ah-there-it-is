"""Host-lock and durable restart boundaries for the Telegram service."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import os

import pytest
from sqlalchemy import func, select

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.config import resolve_database_url
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import ChatRequestRecord, Item
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.chat_application import ChatApplicationService
from ah_there_it_is.telegram.adapter import TelegramAdapter
from ah_there_it_is.telegram.client import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from ah_there_it_is.telegram.polling import TelegramPollingService
from ah_there_it_is.telegram.singleton import TelegramSingletonError, lock_path, telegram_singleton


def test_production_requires_explicit_absolute_sqlite_url(tmp_path: Path) -> None:
    env = {"AH_THERE_IT_IS_ENV": "production"}
    with pytest.raises(ValueError, match="requires AH_THERE_IT_IS_DATABASE_URL"):
        resolve_database_url(env)
    for bad in (" ", "sqlite:///relative.db", "postgresql://user:secret@host/db", "sqlite://"):
        with pytest.raises(ValueError) as error:
            resolve_database_url({**env, "AH_THERE_IT_IS_DATABASE_URL": bad})
        assert "secret" not in str(error.value)
    good = f"sqlite:///{tmp_path / 'inventory.db'}"
    assert resolve_database_url({**env, "AH_THERE_IT_IS_DATABASE_URL": good}) == good


def test_runtime_cli_rejects_invalid_production_config_without_echo(
    monkeypatch, capsys
) -> None:
    from ah_there_it_is.config import get_settings
    from ah_there_it_is.runtime_cli import main

    monkeypatch.setenv("AH_THERE_IT_IS_ENV", "production")
    monkeypatch.setenv("AH_THERE_IT_IS_DATABASE_URL", "postgresql://secret@host/db")
    get_settings.cache_clear()
    try:
        assert main(["serve"]) == 2
    finally:
        get_settings.cache_clear()
    assert "secret" not in capsys.readouterr().err


@pytest.mark.extended
def test_second_process_cannot_hold_telegram_lock(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'inventory.db'}"
    token = "synthetic-bot-token"
    lock_dir = tmp_path / "locks"
    script = (
        "import os, sys; from pathlib import Path; "
        "from ah_there_it_is.telegram.singleton import telegram_singleton; "
        "\nwith telegram_singleton(sys.argv[1], os.environ['PROBE_BOT_TOKEN'], "
        "lock_dir=Path(sys.argv[2])):\n"
        " print('ready', flush=True); sys.stdin.readline()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, database_url, str(lock_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PROBE_BOT_TOKEN": token},
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(TelegramSingletonError, match="already has a poller"):
            with telegram_singleton(database_url, token, lock_dir=lock_dir):
                pytest.fail("second process acquired poller lock")
        assert child.poll() is None
        assert lock_path(database_url).stat().st_mode & 0o777 == 0o600
    finally:
        child.terminate()
        child.communicate(timeout=5)
    with telegram_singleton(database_url, token, lock_dir=lock_dir):
        pass


@pytest.mark.parametrize("crash_after", ["mutation", "reply"])
def test_restart_replays_one_mutation_from_durable_database(
    tmp_path: Path, crash_after: str
) -> None:
    database_url = f"sqlite:///{tmp_path / 'inventory.db'}"
    upgrade_database(database_url)
    update = TelegramUpdate(
        update_id=91,
        message=TelegramMessage(
            message_id=91,
            chat=TelegramChat(id=700, type="private"),
            from_user=TelegramUser(id=7),
            text="Создай предмет Резервная гайка",
        ),
    )
    sent: list[str] = []

    class Client:
        def __init__(self, attempt: int) -> None:
            self.attempt = attempt

        def get_updates(self, **_kwargs):
            return [update]

        def send_message(self, _chat_id: int, content: str):
            if crash_after == "mutation" and self.attempt == 0:
                raise RuntimeError("crash before external reply")
            sent.append(content)
            return ()

    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    try:
        for attempt in (0, 1):
            with factory() as session:
                llm = ScriptedLLMClient(
                    [
                        LLMResponse(tool_calls=(ToolCall(id="search", name="search_items", arguments={"query": "Резервная гайка"}),)),
                        LLMResponse(tool_calls=(ToolCall(id="create", name="create_item", arguments={"name": "Резервная гайка"}),)),
                        LLMResponse(content="Сохранено."),
                    ]
                )
                client = Client(attempt)
                adapter = TelegramAdapter(
                    session, ChatApplicationService(session, lambda: llm), client,
                    allowed_user_id=7,
                )
                if crash_after == "reply" and attempt == 0:
                    adapter.acknowledge_update = lambda _id: (_ for _ in ()).throw(  # type: ignore[method-assign]
                        RuntimeError("crash before checkpoint")
                    )
                poller = TelegramPollingService(adapter, client)
                if attempt == 0:
                    with pytest.raises(RuntimeError, match="crash"):
                        poller.run_once()
                    assert adapter.next_offset() == 0
                else:
                    assert poller.run_once().next_offset == 92
                    assert llm.remaining == 3  # replay used the committed receipt
        with factory() as session:
            assert session.scalar(select(func.count(Item.id))) == 1
            assert session.scalar(select(func.count(ChatRequestRecord.id))) == 1
        assert len(sent) == (1 if crash_after == "mutation" else 2)
    finally:
        engine.dispose()
