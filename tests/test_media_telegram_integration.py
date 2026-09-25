from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.db.models import ChatRequestRecord, Event, Item, ItemMedia
from ah_there_it_is.domain.exceptions import DuplicateEntityError
from ah_there_it_is.services.chat_application import ChatApplicationService
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.telegram.adapter import TelegramAdapter
from ah_there_it_is.telegram.client import (
    MAX_TELEGRAM_TEXT_LENGTH,
    TelegramChat,
    TelegramBotClient,
    TelegramMessage,
    TelegramUpdate,
    TelegramUser,
)
from ah_there_it_is.telegram.polling import TelegramPollingService


def _update(
    update_id: int,
    *,
    user_id: int = 7,
    chat_id: int = 700,
    chat_type: str = "private",
    text: str | None = "hello",
) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=(
            TelegramMessage(
                message_id=update_id,
                chat=TelegramChat(id=chat_id, type=chat_type),
                from_user=TelegramUser(id=user_id) if user_id >= 0 else None,
                text=text,
            )
            if text is not None or user_id >= 0
            else None
        ),
    )


class _PollingClient:
    def __init__(self, batches, *, fail_sends: int = 0) -> None:
        self.batches = [list(batch) for batch in batches]
        self.poll_offsets: list[int] = []
        self.sent: list[tuple[int, str]] = []
        self.fail_sends = fail_sends

    def get_updates(self, *, offset: int, timeout: int, limit: int):
        self.poll_offsets.append(offset)
        if not self.batches:
            return []
        return list(self.batches[min(len(self.poll_offsets) - 1, len(self.batches) - 1)])

    def send_message(self, chat_id: int, text: str):
        if self.fail_sends:
            self.fail_sends -= 1
            raise RuntimeError("sendMessage unavailable")
        self.sent.append((chat_id, text))
        return ()


def test_media_scale_keeps_order_duplicate_boundaries_and_equivalent_lot_ids(session) -> None:
    inventory = InventoryService(session)
    lots = [
        inventory.create_item("Equivalent integration lot", allow_duplicate=True)
        for _ in range(60)
    ]
    for item in lots:
        inventory.attach_item_photo(item.id, "catalog", f"{item.id}-back", position=2)
        inventory.attach_item_photo(item.id, "catalog", f"{item.id}-front", position=0)
        inventory.attach_item_photo(item.id, "catalog", f"{item.id}-side", position=1)

    assert len({item.id for item in lots}) == 60
    assert all(
        [photo.media_reference for photo in inventory.list_item_photos(item.id)]
        == [f"{item.id}-front", f"{item.id}-side", f"{item.id}-back"]
        for item in lots
    )
    with pytest.raises(DuplicateEntityError):
        inventory.attach_item_photo(lots[0].id, "catalog", f"{lots[0].id}-front")
    assert session.scalar(select(func.count(ItemMedia.id))) == 180
    assert not session.scalar(
        select(func.count(ItemMedia.id)).where(ItemMedia.media_reference.like("%bytes%"))
    )


def test_media_failure_before_outer_commit_does_not_corrupt_inventory(session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Resolver boundary item")
    before_events = int(session.scalar(select(func.count(Event.id))) or 0)
    transactional = InventoryService(session, autocommit=False)

    with pytest.raises(RuntimeError, match="resolver unavailable"):
        transactional.attach_item_photo(item.id, "external", "opaque-ref")
        raise RuntimeError("resolver unavailable")
    session.rollback()

    assert inventory.list_item_photos(item.id) == []
    assert int(session.scalar(select(func.count(Event.id))) or 0) == before_events


def test_media_remove_restore_and_split_keep_associations_on_source_only(session) -> None:
    inventory = InventoryService(session)
    shelf = inventory.create_location("Integration shelf")
    bin_ = inventory.create_location("Integration bin")
    source = inventory.create_item("Photo-bearing bolts", location_id=shelf.id, quantity=10)
    first = inventory.attach_item_photo(source.id, "catalog", "bolts-front")
    second = inventory.attach_item_photo(source.id, "catalog", "bolts-back", position=1)

    child = inventory.move_item(
        source.id,
        bin_.id,
        portion={"mode": "exact", "value": 3},
    )
    assert [photo.id for photo in inventory.list_item_photos(source.id)] == [
        first.id,
        second.id,
    ]
    assert inventory.list_item_photos(child.id) == []

    inventory.remove_item(source.id, reason="integration cleanup", reason_source="explicit")
    inventory.restore_item(source.id, state="unknown", location_id=None)
    assert [photo.id for photo in inventory.list_item_photos(source.id)] == [
        first.id,
        second.id,
    ]


def test_telegram_replay_after_send_failure_commits_once_and_persists_source_identity(
    session,
) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(id="search", name="search_items", arguments={"query": "Telegram integration item"}),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(id="create", name="create_item", arguments={"name": "Telegram integration item"}),
                )
            ),
            LLMResponse(content="Stored once."),
        ]
    )
    application = ChatApplicationService(session, lambda: llm)
    client = _PollingClient([[_update(9001, text="Create Telegram integration item")]] * 2, fail_sends=1)
    adapter = TelegramAdapter(session, application, client, allowed_user_id=7)
    polling = TelegramPollingService(adapter, client)

    with pytest.raises(RuntimeError, match="sendMessage unavailable"):
        polling.run_once()
    assert adapter.next_offset() == 0

    result = polling.run_once()

    assert result.next_offset == 9002
    assert llm.remaining == 0
    assert session.scalar(select(func.count(Item.id))) == 1
    request = session.scalar(
        select(ChatRequestRecord).where(ChatRequestRecord.request_key == "telegram:9001")
    )
    assert request is not None
    assert request.source_identity == "telegram:7"
    assert client.poll_offsets == [0, 0]
    assert client.sent == [(700, "Stored once.")]


def test_telegram_policy_discards_unauthorized_group_and_non_text_without_media_side_effect(
    session,
) -> None:
    calls: list[dict] = []

    def execute_chat(message: str, **kwargs):
        calls.append({"message": message, **kwargs})
        return SimpleNamespace(
            result=SimpleNamespace(conversation_id=1, content="ignored"),
        )

    class Client:
        def send_message(self, *_args):
            raise AssertionError("rejected updates must not send")

    adapter = TelegramAdapter(session, SimpleNamespace(execute_chat=execute_chat), Client(), allowed_user_id=7)
    assert adapter.process_update(_update(1, user_id=8)).accepted is False
    assert adapter.process_update(_update(2, chat_type="group")).accepted is False
    assert adapter.process_update(
        TelegramUpdate(update_id=3, message=None)
    ).accepted is False
    assert calls == []
    assert session.scalar(select(func.count(ItemMedia.id))) == 0


def test_telegram_long_text_limit_remains_transport_only() -> None:
    bodies: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        message_id = len(bodies)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": message_id,
                    "chat": {"id": 700, "type": "private"},
                    "from": {"id": 7},
                    "text": "ok",
                },
            },
        )

    text = "x" * (MAX_TELEGRAM_TEXT_LENGTH + 1)
    with TelegramBotClient(
        "token",
        base_url="https://telegram.test",
        transport=httpx.MockTransport(respond),
    ) as client:
        client.send_message(700, text)

    assert [len(body["text"]) for body in bodies] == [MAX_TELEGRAM_TEXT_LENGTH, 1]
    assert all("media_reference" not in body["text"] for body in bodies)
