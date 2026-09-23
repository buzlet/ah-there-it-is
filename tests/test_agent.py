from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import AgentLoopLimitError
from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.services import InventoryService
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.db.models import Item


def call(call_id: str, tool_name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=tool_name, arguments=arguments)


def test_agent_searches_then_moves_by_resolved_ids(session: Session) -> None:
    inventory = InventoryService(session)
    desk = inventory.create_location("Стол")
    drawer = inventory.create_location("Ящик", parent_id=desk.id)
    balcony = inventory.create_location("Балкон")
    item = inventory.create_item("DT-830B", location_id=drawer.id)

    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="DT-830B"),)),
            LLMResponse(tool_calls=(call("2", "search_locations", query="Балкон"),)),
            LLMResponse(
                tool_calls=(
                    call("3", "move_item", item_id=item.id, location_id=balcony.id),
                )
            ),
            LLMResponse(content="Переложил DT-830B на балкон."),
        ]
    )

    result = AgentRunner(session, llm).run("Переложил DT-830B на балкон")

    assert result.content == "Переложил DT-830B на балкон."
    assert inventory.get_item(item.id).current_location_id == balcony.id
    history = inventory.get_item_history(item.id)
    assert history[-1].original_text == "Переложил DT-830B на балкон"


def test_guessed_mutation_id_is_rejected_without_write(session: Session) -> None:
    inventory = InventoryService(session)
    location = inventory.create_location("Балкон")
    item = inventory.create_item("Adapter")
    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    call("1", "move_item", item_id=item.id, location_id=location.id),
                )
            ),
            LLMResponse(content="Нужно сначала уточнить предмет и место."),
        ]
    )

    AgentRunner(session, llm).run("Переложи адаптер на балкон")

    assert inventory.get_item(item.id).current_location_id is None
    tool_message = llm.calls[1][0][-1]
    payload = json.loads(tool_message.content)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ToolPreconditionError"


def test_create_item_requires_search_then_allows_creation(session: Session) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="HDMI cable"),)),
            LLMResponse(
                tool_calls=(
                    call(
                        "2",
                        "create_item",
                        name="HDMI cable",
                        state="new",
                        quantity=2,
                        tags=["HDMI"],
                    ),
                )
            ),
            LLMResponse(content="Запомнил два новых HDMI-кабеля."),
        ]
    )

    AgentRunner(session, llm).run("У меня два новых HDMI кабеля")

    inventory = InventoryService(session)
    created = inventory.get_item(1)
    assert created.name == "HDMI cable"
    assert created.quantity == 2
    assert created.state == "new"


def test_create_accepts_prior_search_with_same_tokens_reordered(session: Session) -> None:
    dispatcher = ToolDispatcher(session)

    searched = dispatcher.execute(
        "search_items",
        {"query": "Anker 7-в-1 USB-C hub"},
    )
    created = dispatcher.execute(
        "create_item",
        {"name": "USB-C hub Anker 7-в-1"},
    )

    assert searched["ok"] is True
    assert searched["result"] == []
    assert created["ok"] is True
    assert created["result"]["name"] == "USB-C hub Anker 7-в-1"


def test_create_without_matching_prior_search_is_rejected(session: Session) -> None:
    dispatcher = ToolDispatcher(session)

    result = dispatcher.execute("create_item", {"name": "USB hub"})

    assert result["ok"] is False
    assert result["error"]["type"] == "ToolPreconditionError"


def test_ambiguity_can_end_in_clarification_without_mutation(session: Session) -> None:
    inventory = InventoryService(session)
    inventory.create_item("DT-830B", description="Красный мультиметр")
    inventory.create_item("UNI-T UT61E", description="Чёрный мультиметр")
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="мультиметр"),)),
            LLMResponse(content="Какой мультиметр: красный DT-830B или UNI-T UT61E?"),
        ]
    )

    result = AgentRunner(session, llm).run("Переложил мультиметр")

    assert "Какой мультиметр" in result.content
    assert all(item.current_location_id is None for item in session.query(type(inventory.get_item(1))).all())


def test_conversation_persists_only_human_visible_turns(session: Session) -> None:
    first_llm = ScriptedLLMClient([LLMResponse(content="Какой именно адаптер?")])
    first = AgentRunner(session, first_llm).run("Переложил адаптер")

    second_llm = ScriptedLLMClient([LLMResponse(content="Понял: USB-SATA.")])
    second = AgentRunner(session, second_llm).run(
        "USB-SATA", conversation_id=first.conversation_id
    )

    assert second.conversation_id == first.conversation_id
    messages = ConversationService(session).list_messages(first.conversation_id)
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Переложил адаптер"),
        ("assistant", "Какой именно адаптер?"),
        ("user", "USB-SATA"),
        ("assistant", "Понял: USB-SATA."),
    ]
    sent = second_llm.calls[0][0]
    assert [(message.role, message.content) for message in sent[1:]] == [
        ("user", "Переложил адаптер"),
        ("assistant", "Какой именно адаптер?"),
        ("user", "USB-SATA"),
    ]


def test_invalid_and_unknown_tool_calls_return_structured_errors(session: Session) -> None:
    dispatcher = ToolDispatcher(session)

    invalid = dispatcher.execute("search_items", {"query": "x", "limit": 0})
    unknown = dispatcher.execute("drop_database", {})

    assert invalid["ok"] is False
    assert invalid["error"]["type"] == "invalid_arguments"
    assert unknown == {
        "ok": False,
        "error": {"type": "unknown_tool", "detail": "unknown tool: drop_database"},
    }


def test_tool_schema_mutations_are_id_based(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Adapter")
    location = inventory.create_location("Балкон")
    dispatcher = ToolDispatcher(session)
    dispatcher.execute("search_items", {"query": "Adapter"})
    dispatcher.execute("search_locations", {"query": "Балкон"})
    definitions = {tool.name: tool for tool in dispatcher.definitions()}

    assert item.id in dispatcher.state.resolved["item"]
    assert location.id in dispatcher.state.resolved["location"]
    move_props = definitions["move_item"].input_schema["properties"]
    assert set(move_props) == {"item_id", "location_id"}
    assert "item" not in move_props
    assert "location" not in move_props


def test_tool_definitions_expand_from_backend_capabilities(session: Session) -> None:
    inventory = InventoryService(session)
    inventory.create_item("Adapter")
    inventory.create_location("Балкон")
    dispatcher = ToolDispatcher(session)

    initial = {tool.name for tool in dispatcher.definitions()}
    assert initial == {
        "search_items",
        "search_locations",
        "search_categories",
        "search_tags",
    }

    dispatcher.execute("search_items", {"query": "Adapter"})
    after_item = {tool.name for tool in dispatcher.definitions()}
    assert {"get_item", "get_item_history", "update_item", "move_item"} <= after_item
    assert "create_item" not in after_item
    assert "get_location" not in after_item

    dispatcher.execute("search_locations", {"query": "Балкон"})
    after_location = {tool.name for tool in dispatcher.definitions()}
    assert {"get_location", "list_location", "move_item"} <= after_location
    assert "create_location" not in after_location

    dispatcher.execute("search_items", {"query": "Never Seen Widget"})
    after_empty_item = {tool.name for tool in dispatcher.definitions()}
    assert "create_item" in after_empty_item


def test_ambiguous_location_search_hides_move_until_refined(session: Session) -> None:
    inventory = InventoryService(session)
    inventory.create_item("Adapter")
    room_a = inventory.create_location("Комната A")
    room_b = inventory.create_location("Комната B")
    inventory.create_location("Шкаф", parent_id=room_a.id)
    inventory.create_location("Шкаф", parent_id=room_b.id)
    dispatcher = ToolDispatcher(session)

    dispatcher.execute("search_items", {"query": "Adapter"})
    assert "move_item" in {tool.name for tool in dispatcher.definitions()}

    dispatcher.execute("search_locations", {"query": "Шкаф"})
    ambiguous = {tool.name for tool in dispatcher.definitions()}
    assert "move_item" not in ambiguous

    dispatcher.execute("search_locations", {"query": "Комната A"})
    refined = {tool.name for tool in dispatcher.definitions()}
    assert "move_item" in refined


def test_compact_tool_schema_drops_pydantic_titles_and_defaults(session: Session) -> None:
    dispatcher = ToolDispatcher(session)
    search = {tool.name: tool for tool in dispatcher.definitions()}["search_items"]
    encoded = json.dumps(search.input_schema)

    assert '"title"' not in encoded
    assert '"default"' not in encoded
    assert search.input_schema["properties"]["query"]["minLength"] == 1


def test_agent_refreshes_tool_definitions_after_search(session: Session) -> None:
    inventory = InventoryService(session)
    inventory.create_item("Adapter")
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="Adapter"),)),
            LLMResponse(content="Нашёл."),
        ]
    )

    AgentRunner(session, llm).run("Где Adapter?")

    first_tools = {tool.name for tool in llm.calls[0][1]}
    second_tools = {tool.name for tool in llm.calls[1][1]}
    assert first_tools == {
        "search_items",
        "search_locations",
        "search_categories",
        "search_tags",
    }
    assert {"get_item", "get_item_history", "update_item", "move_item"} <= second_tools


def test_agent_loop_has_hard_round_limit(session: Session) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="x"),)),
            LLMResponse(tool_calls=(call("2", "search_items", query="x"),)),
        ]
    )

    with pytest.raises(AgentLoopLimitError):
        AgentRunner(session, llm, max_rounds=2).run("ищи x")


def test_created_parent_becomes_resolved_for_child_creation(session: Session) -> None:
    dispatcher = ToolDispatcher(session)
    assert dispatcher.execute("search_locations", {"query": "Балкон"})["ok"] is True
    balcony = dispatcher.execute("create_location", {"name": "Балкон"})
    balcony_id = balcony["result"]["id"]

    assert dispatcher.execute("search_locations", {"query": "Полка 1"})["ok"] is True
    shelf = dispatcher.execute(
        "create_location", {"name": "Полка 1", "parent_id": balcony_id}
    )

    assert shelf["ok"] is True
    assert shelf["result"]["path"] == "Балкон / Полка 1"


def test_heuristic_client_can_run_offline_where_query(session: Session) -> None:
    from ah_there_it_is.agent import HeuristicLLMClient

    inventory = InventoryService(session)
    balcony = inventory.create_location("Балкон")
    item = inventory.create_item("CH341A", location_id=balcony.id)

    result = AgentRunner(session, HeuristicLLMClient()).run("Где CH341A?")

    assert item.name in result.content
    assert "Балкон" in result.content


def test_heuristic_client_can_create_item_in_existing_location(session: Session) -> None:
    from ah_there_it_is.agent import HeuristicLLMClient

    inventory = InventoryService(session)
    desk = inventory.create_location("Стол")
    drawer = inventory.create_location("правый ящик", parent_id=desk.id)

    result = AgentRunner(session, HeuristicLLMClient()).run(
        "Положил USB тестер в правый ящик"
    )

    created = session.query(Item).filter_by(name="USB тестер").one()
    assert created.current_location_id == drawer.id
    assert "Стол / правый ящик" in result.content


def test_ambiguous_candidates_are_seen_but_not_mutation_resolved(session: Session) -> None:
    inventory = InventoryService(session)
    category = inventory.create_category("Мультиметры")
    first = inventory.create_item("Meter", category_id=category.id)
    second = inventory.create_item("Meter", category_id=category.id, allow_duplicate=True)
    balcony = inventory.create_location("Балкон")
    dispatcher = ToolDispatcher(session)

    found = dispatcher.execute("search_items", {"query": "Meter"})
    assert [candidate["id"] for candidate in found["result"]] == [first.id, second.id]
    assert dispatcher.execute("search_locations", {"query": "Балкон"})["ok"] is True

    read = dispatcher.execute("get_item", {"id": first.id})
    attempted_move = dispatcher.execute(
        "move_item", {"item_id": first.id, "location_id": balcony.id}
    )

    assert read["ok"] is True
    assert attempted_move["ok"] is False
    assert attempted_move["error"]["type"] == "ToolPreconditionError"
    assert inventory.get_item(first.id).current_location_id is None


def test_unique_exact_identity_resolves_despite_weaker_candidates(session: Session) -> None:
    inventory = InventoryService(session)
    exact = inventory.create_item("Chieftec 750W")
    inventory.create_item(
        "Other PSU",
        description="Stored next to Chieftec 750W",
    )
    balcony = inventory.create_location("Балкон")
    dispatcher = ToolDispatcher(session)

    results = dispatcher.execute("search_items", {"query": "Chieftec 750W"})
    assert results["result"][0]["id"] == exact.id
    assert len(results["result"]) == 2
    dispatcher.execute("search_locations", {"query": "Балкон"})

    moved = dispatcher.execute(
        "move_item", {"item_id": exact.id, "location_id": balcony.id}
    )

    assert moved["ok"] is True
    assert inventory.get_item(exact.id).current_location_id == balcony.id


def test_same_round_search_cannot_authorize_same_round_mutation(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Adapter")
    balcony = inventory.create_location("Балкон")
    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    call("1", "search_items", query="Adapter"),
                    call("2", "search_locations", query="Балкон"),
                    call("3", "move_item", item_id=item.id, location_id=balcony.id),
                )
            ),
            LLMResponse(
                tool_calls=(
                    call("4", "move_item", item_id=item.id, location_id=balcony.id),
                )
            ),
            LLMResponse(content="Готово."),
        ]
    )

    AgentRunner(session, llm).run("Переложи Adapter на Балкон")

    first_round_messages = llm.calls[1][0]
    failed_move = json.loads(first_round_messages[-1].content)
    assert failed_move["ok"] is False
    assert failed_move["error"]["type"] == "ToolPreconditionError"
    assert inventory.get_item(item.id).current_location_id == balcony.id


def test_location_suggestions_require_resolved_item(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Unresolved item")
    dispatcher = ToolDispatcher(session)

    assert "suggest_item_locations" not in {
        tool.name for tool in dispatcher.definitions()
    }
    result = dispatcher.execute(
        "suggest_item_locations",
        {"item_id": item.id},
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "ToolPreconditionError"


def test_suggested_location_is_seen_but_does_not_authorize_move(
    session: Session,
) -> None:
    from sqlalchemy import func, select

    from ah_there_it_is.db.models import Event

    inventory = InventoryService(session)
    category = inventory.create_category("Adapters")
    location = inventory.create_location("Drawer")
    target = inventory.create_item("Target adapter", category_id=category.id)
    inventory.create_item(
        "Related adapter",
        category_id=category.id,
        location_id=location.id,
    )
    dispatcher = ToolDispatcher(session)

    searched = dispatcher.execute("search_items", {"query": "Target adapter"})
    assert searched["ok"] is True
    assert target.id in dispatcher.state.resolved["item"]
    assert "suggest_item_locations" in {
        tool.name for tool in dispatcher.definitions()
    }

    events_before = int(session.scalar(select(func.count(Event.id))) or 0)
    suggested = dispatcher.execute(
        "suggest_item_locations",
        {"item_id": target.id},
    )
    assert suggested["ok"] is True
    assert suggested["result"]["stored_current_location_id"] is None
    assert suggested["result"]["suggestions"][0]["location_id"] == location.id
    assert location.id in dispatcher.state.seen["location"]
    assert location.id not in dispatcher.state.resolved["location"]

    read = dispatcher.execute("get_location", {"id": location.id})
    attempted_move = dispatcher.execute(
        "move_item",
        {"item_id": target.id, "location_id": location.id},
    )

    assert read["ok"] is True
    assert attempted_move["ok"] is False
    assert attempted_move["error"]["type"] == "ToolPreconditionError"
    assert inventory.get_item(target.id).current_location_id is None
    assert int(session.scalar(select(func.count(Event.id))) or 0) == events_before
