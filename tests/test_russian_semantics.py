from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import ToolClarificationRequiredError
from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.config import Settings, get_settings
from ah_there_it_is.db.models import Event, Location
from ah_there_it_is.domain.russian_semantics import (
    canonicalize_location_name, canonicalize_name,
)
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.inventory import InventoryService
from ah_there_it_is.services.search import SearchService


def _call(call_id: str, tool_name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=tool_name, arguments=arguments)


def _run_location_create(
    session: Session, phrase: str, *, policy: str = "physical"
) -> dict[str, object]:
    dispatcher = ToolDispatcher(session, location_containment_policy=policy)
    search = dispatcher.execute("search_locations", {"query": phrase})
    assert search["ok"] is True
    return dispatcher.execute("create_location", {"name": phrase})


def test_canonicalization_normalizes_inflection_case_spacing_and_punctuation(session: Session) -> None:
    assert canonicalize_name("ЗУБНУЮ   ЩЁТКУ!!!").display_name == "зубная щётка"
    assert canonicalize_name("туалетной бумаги").comparison_key == "туалетная бумага"
    assert canonicalize_location_name("в ванной").display_name == "ванна"
    assert canonicalize_location_name("в тумбочке").display_name == "тумбочка"
    assert canonicalize_name("в ванной").display_name != "ванна"
    assert canonicalize_location_name("на верхней полке").display_name == "верхняя полка"
    assert canonicalize_name('  «СТАРАЯ ЩЁТКА!»  ').display_name == "старая щётка"
    assert canonicalize_name("USB—кабель").display_name == "USB-кабель"

    inventory = InventoryService(session)
    item = inventory.create_item("  ЗУБНУЮ\u00a0ЩЁТКУ!!! ")
    location = inventory.create_location("в ванной")
    assert item.name == "зубная щётка"
    assert item.normalized_name == "зубная щётка"
    assert location.name == "ванна"
    assert location.normalized_name == "ванна"


def test_technical_and_brand_casing_is_preserved(session: Session) -> None:
    inventory = InventoryService(session)
    cable = inventory.create_item("USB-кабель")
    storage = inventory.create_item("SSD Samsung")
    assert cable.name == "USB-кабель"
    assert storage.name == "SSD Samsung"
    assert cable.normalized_name == "usb-кабель"
    assert storage.normalized_name == "ssd samsung"


def test_russian_tags_use_the_same_canonical_display_and_identity(session: Session) -> None:
    InventoryService(session).create_item("Тестовый прибор", tags=["Туалетной бумаги"])

    result = SearchService(session).search_tags("туалетной бумаге")

    assert len(result) == 1
    assert result[0].name == "туалетная бумага"
    assert result[0].match_type == "exact_name"


def test_inflected_query_is_a_strong_canonical_match(session: Session) -> None:
    item = InventoryService(session).create_item("Туалетная бумага")
    dispatcher = ToolDispatcher(session)

    result = dispatcher.execute("search_items", {"query": "туалетной бумаги"})

    assert [row["id"] for row in result["result"]] == [item.id]
    assert item.name == "туалетная бумага"
    assert item.id in dispatcher.state.resolved["item"]
    assert dispatcher.trace_evidence()["identity"]["evidence"] == "canonical_name"


def test_generic_head_retrieval_cannot_authorize_mutation_or_reuse(session: Session) -> None:
    inventory = InventoryService(session)
    specific = inventory.create_item("туалетная бумага")
    dispatcher = ToolDispatcher(session)

    search = dispatcher.execute("search_items", {"query": "бумага"})

    assert any(row["id"] == specific.id for row in search["result"])
    assert specific.id in dispatcher.state.seen["item"]
    assert specific.id not in dispatcher.state.resolved["item"]
    assert "create_item" in {tool.name for tool in dispatcher.definitions()}
    assert dispatcher.trace_evidence()["identity"]["decision"] == "weak_retrieval_only"
    before_events = int(session.scalar(select(func.count(Event.id))) or 0)
    rejected = dispatcher.execute(
        "update_item", {"item_id": specific.id, "description": "wrong target"}
    )
    assert rejected["ok"] is False
    assert inventory.get_item(specific.id).description is None
    assert int(session.scalar(select(func.count(Event.id))) or 0) == before_events

    generic = dispatcher.execute("create_item", {"name": "бумага"})
    assert generic["ok"] is True
    assert generic["result"]["id"] != specific.id
    assert generic["result"]["name"] == "бумага"


def test_scripted_agent_creates_item_and_nested_location_with_receipts(session: Session) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(_call("1", "search_items", query="зубную щётку"),)),
            LLMResponse(tool_calls=(
                _call("2", "search_locations", query="в тумбочке в ванной"),
            )),
            LLMResponse(tool_calls=(
                _call("3", "create_location", name="в тумбочке в ванной"),
            )),
            LLMResponse(tool_calls=(
                _call("4", "create_item", name="зубную щётку", location_id=2),
            )),
            LLMResponse(content="Запомнил зубную щётку в тумбочке в ванной."),
        ]
    )

    result = AgentRunner(session, llm).run("зубную щётку в тумбочке в ванной")

    item = InventoryService(session).get_item(1)
    assert item.name == "зубная щётка"
    assert item.current_location is not None
    assert item.current_location.name == "тумбочка"
    assert item.current_location.parent is not None
    assert item.current_location.parent.name == "ванна"
    assert result.receipts[0].operation == "create_location"
    assert result.receipts[0].created_location_ids == (1, 2)
    assert result.receipts[1].operation == "create_item"
    run = EvaluationService(session).get_run(result.run_id)
    evidence = run.tool_trace[0]["tool_results"][0]["semantic_evidence"]
    assert evidence["normalization"]["canonical_name"] == "зубная щётка"
    serialized_evidence = json.dumps(
        [round_["tool_results"] for round_ in run.tool_trace], ensure_ascii=False
    )
    assert "api-secret" not in serialized_evidence


def test_existing_parent_is_reused_by_canonical_identity(session: Session) -> None:
    inventory = InventoryService(session)
    bath = inventory.create_location("ванна")
    created = _run_location_create(session, "в тумбочке в ванной")

    assert created["ok"] is True
    assert created["result"]["path"] == "ванна / тумбочка"
    assert created["result"]["parent_id"] == bath.id
    assert created["result"]["created_location_ids"] == [2]
    assert session.scalar(select(func.count(Location.id))) == 2
    assert bath.name == "ванна"


def test_three_level_location_phrase_keeps_outer_to_inner_order(session: Session) -> None:
    created = _run_location_create(session, "в коробке в шкафу в комнате")

    assert created["ok"] is True
    assert created["result"]["path"] == "комната / шкаф / коробка"
    assert created["result"]["created_location_ids"] == [1, 2, 3]


def test_inside_and_on_relations_become_ordered_tree_edges(session: Session) -> None:
    inside = _run_location_create(session, "кабель внутри коробки")
    on_surface = _run_location_create(session, "книга на столе")

    assert inside["result"]["path"] == "коробка / кабель"
    assert on_surface["result"]["path"] == "стол / книга"


def test_direct_service_rejects_flat_relational_location_name(session: Session) -> None:
    inventory = InventoryService(session)

    with pytest.raises(ValueError, match="structured path"):
        inventory.create_location("тумбочка в ванной")

    assert session.scalar(select(func.count(Location.id))) == 0


def test_physical_policy_clarifies_implausible_hierarchy_without_writing(session: Session) -> None:
    dispatcher = ToolDispatcher(session)
    phrase = "комната в ящике"
    dispatcher.execute("search_locations", {"query": phrase})

    result = dispatcher.execute("create_location", {"name": phrase})

    assert result["ok"] is False
    assert result["error"]["type"] == ToolClarificationRequiredError.__name__
    assert session.scalar(select(func.count(Location.id))) == 0


def test_physical_policy_clarifies_bedside_cabinet_in_desk_drawer(session: Session) -> None:
    dispatcher = ToolDispatcher(session)
    phrase = "тумбочка в ящике стола"
    dispatcher.execute("search_locations", {"query": phrase})

    result = dispatcher.execute("create_location", {"name": phrase})

    assert result["error"]["type"] == ToolClarificationRequiredError.__name__
    assert session.scalar(select(func.count(Location.id))) == 0


def test_agent_can_turn_physical_policy_result_into_clarification(session: Session) -> None:
    phrase = "комната в ящике"
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(_call("1", "search_locations", query=phrase),)),
            LLMResponse(tool_calls=(_call("2", "create_location", name=phrase),)),
            LLMResponse(content="Уточни: комнату действительно нужно поместить в ящик?"),
        ]
    )

    result = AgentRunner(session, llm).run("Создай комнату в ящике")

    assert result.changes_applied is False
    assert result.content.startswith("Уточни:")
    assert session.scalar(select(func.count(Location.id))) == 0


def test_permissive_policy_allows_abstract_tree_but_keeps_structure(session: Session) -> None:
    created = _run_location_create(
        session, "комната в ящике", policy="permissive"
    )

    assert created["ok"] is True
    assert created["result"]["path"] == "ящик / комната"
    assert created["result"]["created_location_ids"] == [1, 2]


def test_permissive_policy_does_not_allow_repeated_node_or_cycle(session: Session) -> None:
    dispatcher = ToolDispatcher(session, location_containment_policy="permissive")
    phrase = "ящик в ящике"
    dispatcher.execute("search_locations", {"query": phrase})
    rejected = dispatcher.execute("create_location", {"name": phrase})
    assert rejected["error"]["type"] == ToolClarificationRequiredError.__name__
    assert session.scalar(select(func.count(Location.id))) == 0

    location = InventoryService(session).create_location("комната")
    with pytest.raises(ValueError, match="cycle"):
        InventoryService(session).update_location(location.id, parent_id=location.id)


def test_location_containment_setting_defaults_validates_and_reads_environment(monkeypatch) -> None:
    assert Settings().location_containment_policy == "physical"
    assert Settings(location_containment_policy="permissive").location_containment_policy == "permissive"
    with pytest.raises(ValidationError):
        Settings(location_containment_policy="guess")

    monkeypatch.setenv("AH_THERE_IT_IS_LOCATION_CONTAINMENT_POLICY", "permissive")
    get_settings.cache_clear()
    try:
        assert get_settings().location_containment_policy == "permissive"
        monkeypatch.setenv("AH_THERE_IT_IS_LOCATION_CONTAINMENT_POLICY", "unknown")
        get_settings.cache_clear()
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        get_settings.cache_clear()
