from __future__ import annotations

from types import SimpleNamespace

from ah_there_it_is.config import Settings, get_settings
from ah_there_it_is.db.models import Conversation
from ah_there_it_is.telegram.adapter import TelegramAdapter
from ah_there_it_is.telegram.client import TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser


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
