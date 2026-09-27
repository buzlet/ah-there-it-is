from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select

from ah_there_it_is.db.models import ChatRequestRecord, Item, Location
from ah_there_it_is.telegram.adapter import TelegramAdapter, TelegramAdapterResult
from ah_there_it_is.telegram.client import (
    TelegramCallbackQuery,
    TelegramChat,
    TelegramMessage,
    TelegramUpdate,
    TelegramUser,
)
from ah_there_it_is.telegram.navigation import (
    LOCATION_PAGE_SIZE,
    TelegramLocationBrowser,
    TelegramLocationRenderer,
    parse_navigation_callback,
)
from ah_there_it_is.telegram.polling import TelegramPollingService


class _Application:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def execute_chat(self, *_args, **_kwargs):
        self.calls.append((_args, _kwargs))
        raise AssertionError("navigation must never enter the application path")


class _Client:
    def __init__(self, updates: list[TelegramUpdate] | None = None) -> None:
        self.updates = updates or []
        self.sent: list[tuple[int, str]] = []
        self.sent_options: list[dict] = []
        self.edited: list[tuple[int, int, str, dict]] = []
        self.answered: list[str] = []

    def get_updates(self, *, offset: int, timeout: int, limit: int):
        return [update for update in self.updates if update.update_id >= offset]

    def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text))
        self.sent_options.append(kwargs)
        return ()

    def answer_callback_query(self, query_id: str) -> None:
        self.answered.append(query_id)

    def edit_message_text(
        self, chat_id: int, message_id: int, text: str, **kwargs
    ) -> None:
        self.edited.append((chat_id, message_id, text, kwargs))


def _location(
    session,
    location_id: int,
    name: str,
    *,
    parent_id: int | None = None,
) -> Location:
    location = Location(
        id=location_id,
        parent_id=parent_id,
        name=name,
        normalized_name=f"{location_id:04d} {name.casefold()}",
    )
    session.add(location)
    return location


def _item(
    session,
    name: str,
    *,
    location_id: int,
    quantity: int | None,
    quantity_mode: str,
) -> None:
    session.add(
        Item(
            name=name,
            normalized_name=name.casefold(),
            current_location_id=location_id,
            location_status="known",
            quantity=quantity,
            quantity_mode=quantity_mode,
        )
    )


def _message_update(update_id: int, text: str) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=update_id,
            chat=TelegramChat(id=7, type="private"),
            from_user=TelegramUser(id=7),
            text=text,
        ),
    )


def _callback_update(
    update_id: int,
    data: str | None,
    *,
    user_id: int = 7,
    chat_id: int = 7,
    chat_type: str = "private",
    message_from_bot: bool = True,
    inline_message_id: str | None = None,
) -> TelegramUpdate:
    message = TelegramMessage(
        message_id=500,
        chat=TelegramChat(id=chat_id, type=chat_type),
        from_user=TelegramUser(id=900, is_bot=message_from_bot),
        text="Места хранения",
    )
    return TelegramUpdate(
        update_id=update_id,
        message=None,
        callback_query=TelegramCallbackQuery(
            id=f"cb-{update_id}",
            from_user=TelegramUser(id=user_id),
            message=message,
            data=data,
            inline_message_id=inline_message_id,
        ),
    )


def test_compact_location_renderer_formats_quantities_and_escapes_unicode(session) -> None:
    _location(session, 1, "Ванна & <шкаф>")
    _item(
        session,
        "Зубная щётка 🪥",
        location_id=1,
        quantity=2,
        quantity_mode="exact",
    )
    _item(
        session,
        "Туалетная бумага",
        location_id=1,
        quantity=5,
        quantity_mode="approximate",
    )
    _item(
        session,
        "Банка: неизвестное количество",
        location_id=1,
        quantity=None,
        quantity_mode="unknown",
    )
    session.commit()

    view = TelegramLocationBrowser(session).location_contents(1)
    assert view is not None
    rendered = TelegramLocationRenderer().render_location(view)

    assert "Ванна &amp; &lt;шкаф&gt;" in rendered
    assert "• Зубная щётка 🪥 — 2" in rendered
    assert "• Туалетная бумага — ~5" in rendered
    assert "• Банка: неизвестное количество" in rendered
    assert "неизвестное количество —" not in rendered
    assert "**" not in rendered
    assert "хранится" not in rendered
    assert "находится" not in rendered
    assert "Места:" in rendered
    assert "<шкаф>" not in rendered


def test_root_locations_are_bounded_paged_and_buttons_use_stable_ids(session) -> None:
    for location_id in range(1, LOCATION_PAGE_SIZE + 2):
        _location(session, location_id, f"Место {location_id} 東京")
    session.commit()
    browser = TelegramLocationBrowser(session)
    renderer = TelegramLocationRenderer()

    first = browser.root_page(1)
    first_keyboard = renderer.root_keyboard(first)
    assert first.total == LOCATION_PAGE_SIZE + 1
    assert len(first.locations) == LOCATION_PAGE_SIZE
    assert first_keyboard is not None
    callbacks = [
        button["callback_data"]
        for row in first_keyboard["inline_keyboard"]
        for button in row
    ]
    assert "t1:l:1:1" in callbacks
    assert "t1:r:2" in callbacks
    assert not any("Место" in callback for callback in callbacks)

    second = browser.root_page(2)
    assert second.page == 2
    assert [location.id for location in second.locations] == [LOCATION_PAGE_SIZE + 1]
    assert second.total == LOCATION_PAGE_SIZE + 1


def test_locations_command_drills_down_back_and_edits_the_same_message(session) -> None:
    _location(session, 1, "Ванна")
    _location(session, 2, "Тумбочка 東京", parent_id=1)
    _location(session, 3, "Нижний ящик", parent_id=2)
    _item(
        session,
        "Зубная щётка",
        location_id=2,
        quantity=1,
        quantity_mode="exact",
    )
    session.commit()
    app = _Application()
    client = _Client([_message_update(1, "/locations")])
    adapter = TelegramAdapter(session, app, client, allowed_user_id=7)
    poller = TelegramPollingService(adapter, client)

    initial = poller.run_once()
    assert initial.next_offset == 2
    assert app.calls == []
    assert len(client.sent) == 1
    assert "Места хранения" in client.sent[0][1]
    root_markup = client.sent_options[0]["reply_markup"]
    assert root_markup["inline_keyboard"][0][0]["callback_data"] == "t1:l:1:1"

    client.updates = [_callback_update(2, "t1:l:1:1")]
    poller.run_once()
    assert client.answered[-1] == "cb-2"
    assert client.edited[-1][1] == 500
    assert "Ванна" in client.edited[-1][2]
    assert client.edited[-1][3]["reply_markup"]["inline_keyboard"][-1][0]["text"] == "← Все места"

    client.updates = [_callback_update(3, "t1:l:2:1")]
    poller.run_once()
    child_text = client.edited[-1][2]
    assert "Ванна › Тумбочка 東京" in child_text
    assert "• Зубная щётка — 1" in child_text
    child_rows = client.edited[-1][3]["reply_markup"]["inline_keyboard"]
    assert child_rows[-1][0] == {
        "text": "← Назад", "callback_data": "t1:b:2:1"
    }

    client.updates = [_callback_update(4, "t1:b:2:1")]
    poller.run_once()
    assert "Ванна" in client.edited[-1][2]
    assert "Ванна › Тумбочка" not in client.edited[-1][2]
    assert len(client.sent) == 1
    assert app.calls == []
    assert session.scalar(select(func.count(ChatRequestRecord.id))) == 0


def test_child_locations_page_independently_and_deep_back_uses_parent(session) -> None:
    _location(session, 1, "Дом")
    for location_id in range(2, 2 + LOCATION_PAGE_SIZE + 1):
        _location(session, location_id, f"Комната {location_id}", parent_id=1)
    _location(session, 50, "Ящик", parent_id=2)
    session.commit()
    browser = TelegramLocationBrowser(session)
    renderer = TelegramLocationRenderer()

    parent = browser.location_contents(1)
    assert parent is not None
    keyboard = renderer.location_keyboard(parent)
    child_page_controls = [
        button["callback_data"]
        for row in keyboard["inline_keyboard"]
        for button in row
    ]
    assert "t1:c:1:2:1" in child_page_controls
    second_page = browser.location_contents(1, child_page=2)
    assert second_page is not None
    assert second_page.child_page == 2
    assert len(second_page.children) == 1

    deep = browser.location_contents(50)
    assert deep is not None
    assert deep.breadcrumb == "Дом › Комната 2 › Ящик"
    back = parse_navigation_callback("t1:b:50:1")
    assert back is not None and back.kind == "back"


def test_callback_authorization_malformed_and_stale_ids_are_read_only(session) -> None:
    _location(session, 1, "Ванна")
    session.commit()
    app = _Application()
    client = _Client([
        _callback_update(1, "t1:l:1:1", user_id=8),
        _callback_update(2, "t1:delete:1"),
        _callback_update(3, "t1:l:999999:1"),
        _callback_update(4, "t1:l:1:1", chat_type="group"),
        _callback_update(5, "t1:l:1:1", message_from_bot=False),
    ])
    adapter = TelegramAdapter(session, app, client, allowed_user_id=7)
    result = TelegramPollingService(adapter, client).run_once()

    assert result.next_offset == 6
    assert result.discarded == 3
    assert result.processed == 2
    assert client.answered == ["cb-1", "cb-2", "cb-3", "cb-4", "cb-5"]
    assert len(client.edited) == 2
    assert all(text.startswith("Эта кнопка устарела.") for _, _, text, _ in client.edited)
    assert all(options["reply_markup"] == {"inline_keyboard": []} for *_, options in client.edited)
    assert app.calls == []
    assert session.scalar(select(func.count(Item.id))) == 0
    assert session.scalar(select(func.count(ChatRequestRecord.id))) == 0


def test_invalid_callback_payloads_are_bounded_and_never_become_actions() -> None:
    for value in (
        None,
        "t1:r:0",
        "t1:r:9999999999",
        "t1:l:01:1",
        "t1:l:9223372036854775808:1",
        "t1:i:1:9999999999",
        "t1:l:1:1" + "x" * 64,
        "t2:r:1",
        "t1:remove:1",
    ):
        assert parse_navigation_callback(value) is None


def test_natural_location_query_uses_structured_view_on_delivery_and_replay(session) -> None:
    from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
    from ah_there_it_is.services.chat_application import ChatApplicationService

    _location(session, 1, "Ванна & шкаф")
    _item(session, "Бумага", location_id=1, quantity=5, quantity_mode="approximate")
    session.commit()
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(ToolCall(id="s", name="search_locations", arguments={"query": "Ванна"}),)),
        LLMResponse(tool_calls=(ToolCall(id="l", name="list_location", arguments={"location_id": 1}),)),
        LLMResponse(content="**Ванна**: в инвентаре указано неверное количество 99"),
    ])
    client = _Client()
    adapter = TelegramAdapter(session, ChatApplicationService(session, lambda: llm), client, allowed_user_id=7)
    update = _message_update(60, "Что в Ванне?")
    for _ in range(2):
        result = adapter.process_update(update, request_key="telegram:60")
        assert "• Бумага — ~5" in result.content
        assert "**" not in result.content
        assert "99" not in result.content
        assert "Ванна &amp; шкаф" in result.content
        assert client.sent_options[-1]["parse_mode"] == "HTML"
        assert client.sent_options[-1]["reply_markup"]
    assert llm.remaining == 0


def test_paging_preserves_root_return_context(session) -> None:
    _location(session, 1, "Дом")
    for index in range(9):
        _location(session, index + 2, f"Ящик {index}", parent_id=1)
        _item(session, f"Вещь {index}", location_id=1, quantity=1, quantity_mode="exact")
    session.commit()
    client = _Client()
    adapter = TelegramAdapter(session, _Application(), client, allowed_user_id=7)
    adapter.process_callback_update(_callback_update(80, "t1:l:1:2"))
    keyboard = client.edited[-1][3]["reply_markup"]["inline_keyboard"]
    for label in ("Места ›", "Вещи ›"):
        payload = next(b["callback_data"] for row in keyboard for b in row if b["text"] == label)
        adapter.process_callback_update(_callback_update(81, payload))
        rows = client.edited[-1][3]["reply_markup"]["inline_keyboard"]
        assert rows[-1][0]["callback_data"] == "t1:r:2"


def test_cycle_in_stale_hierarchy_fails_safely_without_writes(session) -> None:
    _location(session, 1, "Дом")
    _location(session, 2, "Ящик", parent_id=1)
    session.flush()
    session.get(Location, 1).parent_id = 2
    session.commit()
    client = _Client()
    app = _Application()
    adapter = TelegramAdapter(session, app, client, allowed_user_id=7)
    result = adapter.process_callback_update(_callback_update(90, "t1:l:2:1"))
    assert result.content.startswith("Эта кнопка устарела.")
    assert app.calls == []
    assert session.scalar(select(func.count(ChatRequestRecord.id))) == 0


def test_item_pages_clamp_and_escape_extreme_names(session) -> None:
    from ah_there_it_is.telegram.navigation import ITEM_PAGE_SIZE

    _location(session, 1, "<&>" * 200)
    for index in range(ITEM_PAGE_SIZE + 1):
        _item(session, f"{index} <&>" * 100, location_id=1, quantity=1, quantity_mode="exact")
    session.commit()
    browser = TelegramLocationBrowser(session)
    first = browser.location_contents(1)
    last = browser.location_contents(1, item_page=999999999)
    assert len(first.items) == ITEM_PAGE_SIZE
    assert last.item_page == 2
    assert len(last.items) == 1
    text = TelegramLocationRenderer().render_location(first)
    assert "<&>" not in text
    assert len(text) < 4096
