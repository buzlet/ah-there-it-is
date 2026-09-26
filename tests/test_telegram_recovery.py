"""Telegram-only operator recovery after an interrupted keyed request."""

from __future__ import annotations

from pathlib import Path
import signal
import subprocess
import sys

import pytest
from sqlalchemy import func, select

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.db.migrations import upgrade_database
from ah_there_it_is.db.models import ChatRequestRecord, Item
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.chat_application import ChatApplicationService
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.telegram.adapter import (
    TelegramAdapter, TelegramRecoveryError, TelegramRecoveryRequiredError,
)
from ah_there_it_is.telegram.client import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from ah_there_it_is.telegram.polling import TelegramPollingService


def _update(number: int, name: str) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=number,
        message=TelegramMessage(
            message_id=number,
            chat=TelegramChat(id=700, type="private"),
            from_user=TelegramUser(id=7),
            text=f"Создай предмет {name}",
        ),
    )


def _llm(name: str) -> ScriptedLLMClient:
    return ScriptedLLMClient([
        LLMResponse(tool_calls=(
            ToolCall(id="search", name="search_items", arguments={"query": name}),
        )),
        LLMResponse(tool_calls=(
            ToolCall(id="create", name="create_item", arguments={"name": name}),
        )),
        LLMResponse(content=f"Сохранено: {name}"),
    ])


class _Client:
    def __init__(self, updates: list[TelegramUpdate]) -> None:
        self.updates = updates
        self.sent: list[str] = []

    def get_updates(self, *, offset: int, timeout: int, limit: int):
        return [update for update in self.updates if update.update_id >= offset]

    def send_message(self, _chat_id: int, text: str):
        self.sent.append(text)
        return ()


def _kill_after_reservation(database_url: str, message: str) -> None:
    script = """
import os, signal, sys
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.chat_requests import ChatRequestService
engine = create_db_engine(sys.argv[1])
with create_session_factory(engine)() as session:
    def die(_commit):
        print('reservation committed', flush=True)
        os.kill(os.getpid(), signal.SIGKILL)
    ChatRequestService(session).execute(
        request_key='telegram:101', message=sys.argv[2],
        conversation_id=None, source_identity='telegram:7', operation=die,
    )
"""
    child = subprocess.run(
        [sys.executable, "-c", script, database_url, message],
        capture_output=True, text=True, timeout=10,
    )
    assert child.stdout.strip() == "reservation committed"
    assert child.returncode == -signal.SIGKILL


@pytest.mark.extended
def test_sigkill_reservation_operator_recovery_replays_then_unblocks_next_update(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'inventory.db'}"
    upgrade_database(database_url)
    first = _update(101, "Первая гайка")
    second = _update(102, "Вторая гайка")
    assert first.message is not None
    _kill_after_reservation(database_url, first.message.text or "")

    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    client = _Client([first, second])
    first_llm = _llm("Первая гайка")
    second_llm = _llm("Вторая гайка")
    llms = iter((first_llm, second_llm))
    try:
        with factory() as session:
            source = ChatRequestService(session).get("telegram:101")
            assert source is not None and source.status == "processing"
            assert session.scalar(select(func.count(Item.id))) == 0
            adapter = TelegramAdapter(
                session, ChatApplicationService(session, lambda: next(llms)), client,
                allowed_user_id=7,
            )
            with pytest.raises(TelegramRecoveryRequiredError, match="101"):
                TelegramPollingService(adapter, client).run_once()
            assert adapter.next_offset() == 0
            assert client.sent == []
            recovered = adapter.recover_update(101, attempt=1)
            assert recovered.replayed is False
            with pytest.raises(TelegramRecoveryError, match="completed recovery"):
                adapter.recover_update(101, attempt=2)

        # A fresh process/session receives the original update again, then 102.
        with factory() as session:
            adapter = TelegramAdapter(
                session, ChatApplicationService(session, lambda: next(llms)), client,
                allowed_user_id=7,
            )
            result = TelegramPollingService(adapter, client).run_once()
            assert result.next_offset == 103
            assert result.processed == 2
            assert client.sent == ["Сохранено: Первая гайка", "Сохранено: Вторая гайка"]
            assert session.scalar(select(func.count(Item.id))) == 2
            source = ChatRequestService(session).get("telegram:101")
            recovery = ChatRequestService(session).get("telegram-recovery:101:1")
            assert source is not None and source.status == "processing"
            assert recovery is not None and recovery.status == "completed"
            assert recovery.recovered_from_id == source.id
            assert recovery.recovery_note and "operator" in recovery.recovery_note
            assert first_llm.remaining == second_llm.remaining == 0
    finally:
        engine.dispose()


def test_blocked_queue_exits_bot_cli_without_token_or_restart_loop(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from ah_there_it_is import runtime_cli
    from ah_there_it_is.config import Settings
    import ah_there_it_is.telegram.runtime as telegram_runtime

    token = "synthetic-secret-token"
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'inventory.db'}",
        telegram_bot_token=token,
        telegram_allowed_user_id=7,
    )
    monkeypatch.setattr(runtime_cli, "get_settings", lambda: settings)
    monkeypatch.setattr(runtime_cli, "runtime_schema_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        telegram_runtime, "run_telegram_bot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TelegramRecoveryRequiredError("Telegram update 101 needs operator recovery")
        ),
    )
    assert runtime_cli.main(["telegram-bot"]) == 2
    output = capsys.readouterr()
    assert "operator recovery" in output.err
    assert token not in output.err


def test_failed_request_requires_controlled_recovery(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'inventory.db'}"
    upgrade_database(database_url)
    update = _update(101, "Резервная шайба")
    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    client = _Client([update])
    llm = _llm("Резервная шайба")
    try:
        with factory() as session:
            with pytest.raises(RuntimeError, match="provider failed"):
                ChatRequestService(session).execute(
                    request_key="telegram:101",
                    message=update.message.text if update.message else "",
                    conversation_id=None,
                    source_identity="telegram:7",
                    operation=lambda _commit: (_ for _ in ()).throw(
                        RuntimeError("provider failed")
                    ),
                )
            source = ChatRequestService(session).get("telegram:101")
            assert source is not None and source.status == "failed"
        with factory() as session:
            adapter = TelegramAdapter(
                session, ChatApplicationService(session, lambda: llm), client,
                allowed_user_id=7,
            )
            with pytest.raises(TelegramRecoveryRequiredError, match="101"):
                TelegramPollingService(adapter, client).run_once()
            adapter.recover_update(101, attempt=1)
        with factory() as session:
            adapter = TelegramAdapter(
                session, ChatApplicationService(session, lambda: pytest.fail("LLM reran")),
                client, allowed_user_id=7,
            )
            assert TelegramPollingService(adapter, client).run_once().next_offset == 102
            assert session.scalar(select(func.count(Item.id))) == 1
            assert len(client.sent) == 1
            assert llm.remaining == 0
    finally:
        engine.dispose()


def test_failed_recovery_attempt_can_be_recovered_without_reusing_a_key(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'inventory.db'}"
    upgrade_database(database_url)
    update = _update(101, "Третья шайба")
    engine = create_db_engine(database_url)
    factory = create_session_factory(engine)
    client = _Client([update])
    llm = _llm("Третья шайба")
    try:
        with factory() as session:
            requests = ChatRequestService(session)
            with pytest.raises(RuntimeError, match="initial failure"):
                requests.execute(
                    request_key="telegram:101",
                    message=update.message.text if update.message else "",
                    conversation_id=None,
                    source_identity="telegram:7",
                    operation=lambda _commit: (_ for _ in ()).throw(
                        RuntimeError("initial failure")
                    ),
                )
            with pytest.raises(RuntimeError, match="recovery provider failure"):
                requests.recover(
                    source_request_key="telegram:101",
                    new_request_key="telegram-recovery:101:1",
                    recovery_note="Telegram operator confirmed atomic rollback; attempt 1",
                    operation=lambda _commit: (_ for _ in ()).throw(
                        RuntimeError("recovery provider failure")
                    ),
                )
        with factory() as session:
            adapter = TelegramAdapter(
                session, ChatApplicationService(session, lambda: llm), client,
                allowed_user_id=7,
            )
            status = adapter.recovery_status(101)
            assert [attempt["status"] for attempt in status["attempts"]] == ["failed"]
            adapter.recover_update(101, attempt=2)
        with factory() as session:
            adapter = TelegramAdapter(
                session, ChatApplicationService(session, lambda: pytest.fail("LLM reran")),
                client, allowed_user_id=7,
            )
            assert TelegramPollingService(adapter, client).run_once().next_offset == 102
            first_attempt = ChatRequestService(session).get("telegram-recovery:101:1")
            second_attempt = ChatRequestService(session).get("telegram-recovery:101:2")
            assert first_attempt is not None and second_attempt is not None
            assert first_attempt.status == "failed"
            assert second_attempt.status == "completed"
            assert second_attempt.recovered_from_id == first_attempt.id
            assert session.scalar(select(func.count(Item.id))) == 1
    finally:
        engine.dispose()
