from __future__ import annotations

from types import SimpleNamespace

import pytest

from ah_there_it_is.config import Settings, get_settings
from ah_there_it_is.db.models import ChatRequestRecord, Conversation
from ah_there_it_is.telegram.adapter import TelegramAdapter
from ah_there_it_is.telegram.client import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser
from ah_there_it_is.telegram.polling import TelegramPollingService


class FakeChatService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_conversation_id = 41

    def execute_chat(self, message: str, **kwargs):
        self.calls.append({"message": message, **kwargs})
        result = SimpleNamespace(
            conversation_id=(
                kwargs["conversation_id"]
                if kwargs["conversation_id"] is not None
                else self.next_conversation_id
            ),
            content=f"reply:{message}",
        )
        return SimpleNamespace(result=result)


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))
        return ()


class PollingTelegramClient(FakeTelegramClient):
    def __init__(self, batches, *, fail_sends: int = 0) -> None:
        super().__init__()
        self.batches = [list(batch) for batch in batches]
        self.poll_calls: list[dict[str, int]] = []
        self.fail_sends = fail_sends

    def get_updates(self, *, offset: int, timeout: int, limit: int):
        self.poll_calls.append({"offset": offset, "timeout": timeout, "limit": limit})
        if not self.batches:
            return []
        index = min(len(self.poll_calls) - 1, len(self.batches) - 1)
        return list(self.batches[index])

    def send_message(self, chat_id: int, text: str):
        if self.fail_sends:
            self.fail_sends -= 1
            raise RuntimeError("injected send failure")
        return super().send_message(chat_id, text)


class ReplayAwareChatService(FakeChatService):
    """Small keyed fake that models the durable application boundary."""

    def __init__(self, session, *, fail_calls: int = 0) -> None:
        super().__init__()
        self.session = session
        self.fail_calls = fail_calls
        self.mutations = 0
        self.results: dict[str, SimpleNamespace] = {}

    def execute_chat(self, message: str, **kwargs):
        self.calls.append({"message": message, **kwargs})
        if self.fail_calls:
            self.fail_calls -= 1
            raise RuntimeError("injected application failure")
        key = kwargs["request_key"]
        if key in self.results:
            return SimpleNamespace(result=self.results[key])
        self.mutations += 1
        result = SimpleNamespace(
            conversation_id=41,
            content=f"reply:{message}",
        )
        self.results[key] = result
        self.session.add(
            ChatRequestRecord(
                request_key=key,
                requested_conversation_id=kwargs["conversation_id"],
                message=message,
                source_identity=kwargs["source_identity"],
                status="completed",
            )
        )
        self.session.flush()
        return SimpleNamespace(result=result)


def update(
    update_id: int,
    *,
    user_id: int = 7,
    chat_id: int = 100,
    chat_type: str = "private",
    text: str | None = "hello",
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=update_id,
            chat=TelegramChat(id=chat_id, type=chat_type),
            from_user=TelegramUser(id=user_id) if user_id >= 0 else None,
            text=text,
        ),
    )


def test_only_allowed_private_text_reaches_application_and_mapping_is_reused(session) -> None:
    session.add(Conversation(id=41))
    session.commit()
    application = FakeChatService()
    client = FakeTelegramClient()
    adapter = TelegramAdapter(
        session,
        application,
        client,
        allowed_user_id=7,
    )

    assert adapter.process_update(update(1, user_id=8)).accepted is False
    assert adapter.process_update(update(2, chat_type="group")).accepted is False
    assert adapter.process_update(update(3, text="  ")).accepted is False
    assert application.calls == []

    accepted = adapter.process_update(update(4), request_key="telegram:4")
    assert accepted.accepted and accepted.invoked
    assert application.calls[0]["conversation_id"] is None
    assert application.calls[0]["source_identity"] == "telegram:7"
    assert client.sent == [(100, "reply:hello")]

    accepted_again = adapter.process_update(update(5), request_key="telegram:5")
    assert accepted_again.conversation_id == 41
    assert application.calls[1]["conversation_id"] == 41


def test_telegram_checkpoint_supports_large_update_ids(session) -> None:
    adapter = TelegramAdapter(session, FakeChatService(), FakeTelegramClient(), allowed_user_id=7)
    large = 9_223_372_036_854_000_000
    assert adapter.next_offset() == 0
    assert adapter.acknowledge_update(large) == large + 1
    assert adapter.next_offset() == large + 1
    assert adapter.acknowledge_update(large - 1) == large + 1
    assert adapter.set_next_offset(12) == 12
    assert adapter.next_offset() == 12


def test_polling_orders_updates_discards_unauthorized_and_advances_offset(session) -> None:
    session.add(Conversation(id=41))
    session.commit()
    application = FakeChatService()
    client = PollingTelegramClient(
        [[
            update(12, text="later"),
            update(10, user_id=8, text="reject"),
            update(11, text="first"),
        ]]
    )
    adapter = TelegramAdapter(session, application, client, allowed_user_id=7)

    result = TelegramPollingService(adapter, poll_timeout=17, limit=25).run_once()

    assert result.fetched == 3
    assert result.processed == 2
    assert result.discarded == 1
    assert result.next_offset == 13
    assert [call["request_key"] for call in application.calls] == [
        "telegram:11",
        "telegram:12",
    ]
    assert [call["message"] for call in application.calls] == ["first", "later"]
    assert client.poll_calls == [{"offset": 0, "timeout": 17, "limit": 25}]
    assert adapter.next_offset() == 13


def test_send_failure_leaves_offset_and_replay_reuses_application_result(session) -> None:
    session.add(Conversation(id=41))
    session.commit()
    application = ReplayAwareChatService(session)
    client = PollingTelegramClient([[update(20)], [update(20)]], fail_sends=1)
    adapter = TelegramAdapter(session, application, client, allowed_user_id=7)
    polling = TelegramPollingService(adapter)

    with pytest.raises(RuntimeError, match="send failure"):
        polling.run_once()
    assert adapter.next_offset() == 0

    replay = polling.run_once()

    assert replay.next_offset == 21
    assert replay.processed == 1
    assert application.mutations == 1
    assert len(application.calls) == 2
    assert application.calls[0]["conversation_id"] is None
    # The durable request was reserved with no conversation before the first
    # binding existed; replay must preserve that exact idempotency payload.
    assert application.calls[1]["conversation_id"] is None
    assert client.sent == [(100, "reply:hello")]
    assert [call["offset"] for call in client.poll_calls] == [0, 0]


def test_checkpoint_failure_allows_duplicate_reply_but_not_duplicate_mutation(session) -> None:
    session.add(Conversation(id=41))
    session.commit()
    application = ReplayAwareChatService(session)
    client = PollingTelegramClient([[update(30)], [update(30)]])
    adapter = TelegramAdapter(session, application, client, allowed_user_id=7)
    polling = TelegramPollingService(adapter)
    original_ack = adapter.acknowledge_update
    failures = 1

    def fail_first_ack(update_id: int) -> int:
        nonlocal failures
        if failures:
            failures -= 1
            raise RuntimeError("injected checkpoint failure")
        return original_ack(update_id)

    adapter.acknowledge_update = fail_first_ack  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="checkpoint failure"):
        polling.run_once()
    assert adapter.next_offset() == 0

    polling.run_once()

    assert adapter.next_offset() == 31
    assert application.mutations == 1
    assert len(client.sent) == 2


def test_telegram_settings_are_optional_until_bot_command(monkeypatch) -> None:
    monkeypatch.setenv("AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN", "token-secret")
    monkeypatch.setenv("AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID", "123456789")
    monkeypatch.setenv("AH_THERE_IT_IS_TELEGRAM_SOURCE_LABEL", "private-bot")
    get_settings.cache_clear()
    settings = get_settings()
    try:
        assert settings.telegram_bot_token == "token-secret"
        assert settings.telegram_allowed_user_id == 123456789
        assert settings.telegram_source_label == "private-bot"
        assert Settings().telegram_bot_token is None
    finally:
        get_settings.cache_clear()
