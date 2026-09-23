from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.experiments import CapturedEvidenceReplay, ExperimentRunner
from ah_there_it_is.agent.tools import ToolRunState
from ah_there_it_is.db.models import Event
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.experiments import ExperimentService
from ah_there_it_is.services.inventory import InventoryService


def _source_search_run(session: Session):
    source = AgentRunner(
        session,
        ScriptedLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(id="s1", name="search_items", arguments={"query": "CH341A"}),)),
                LLMResponse(content="На балконе."),
            ]
        ),
    ).run("Где CH341A?")
    EvaluationService(session).set_feedback(source.run_id, rating=4, comment="baseline")
    return EvaluationService(session).get_run(source.run_id)


def test_experiment_replays_exact_captured_evidence(session: Session) -> None:
    inventory = InventoryService(session)
    balcony = inventory.create_location("Балкон")
    inventory.create_item("CH341A", location_id=balcony.id)
    source = _source_search_run(session)

    variant = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(id="v1", name="search_items", arguments={"query": "CH341A"}),)),
            LLMResponse(content="CH341A находится на балконе."),
        ]
    )
    result = ExperimentRunner(session, variant).run(
        source,
        experiment_name="strict-v2",
        system_prompt="variant prompt",
        prompt_version="inventory-v2",
    )

    assert result.status == "completed"
    stored = ExperimentService(session).get_run(result.experiment_run_id)
    assert stored.source_run_id == source.id
    assert stored.final_content == "CH341A находится на балконе."
    assert stored.tool_trace[0]["tool_results"][0]["source"] == "captured_evidence"


def test_experiment_marks_changed_tool_request_as_diverged(session: Session) -> None:
    inventory = InventoryService(session)
    balcony = inventory.create_location("Балкон")
    inventory.create_item("CH341A", location_id=balcony.id)
    source = _source_search_run(session)

    result = ExperimentRunner(
        session,
        ScriptedLLMClient(
            [LLMResponse(tool_calls=(ToolCall(id="v1", name="search_items", arguments={"query": "программатор"}),))]
        ),
    ).run(
        source,
        experiment_name="different-search",
        system_prompt="variant prompt",
        prompt_version="v2",
    )

    assert result.status == "diverged"
    assert "expected search_items" in (result.divergence_reason or "")


def test_replaying_mutation_does_not_mutate_live_inventory(session: Session) -> None:
    inventory = InventoryService(session)
    desk = inventory.create_location("Стол")
    drawer = inventory.create_location("Ящик", parent_id=desk.id)
    item = inventory.create_item("USB tester")
    source_result = AgentRunner(
        session,
        ScriptedLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(id="1", name="search_items", arguments={"query": "USB tester"}),)),
                LLMResponse(tool_calls=(ToolCall(id="2", name="search_locations", arguments={"query": "Ящик"}),)),
                LLMResponse(tool_calls=(ToolCall(id="3", name="move_item", arguments={"item_id": item.id, "location_id": drawer.id}),)),
                LLMResponse(content="Перемещено."),
            ]
        ),
    ).run("Переложил USB tester в Ящик")
    source = EvaluationService(session).get_run(source_result.run_id)
    before = session.scalar(select(func.count(Event.id)))

    variant = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(ToolCall(id="a", name="search_items", arguments={"query": "USB tester"}),)),
            LLMResponse(tool_calls=(ToolCall(id="b", name="search_locations", arguments={"query": "Ящик"}),)),
            LLMResponse(tool_calls=(ToolCall(id="c", name="move_item", arguments={"item_id": item.id, "location_id": drawer.id}),)),
            LLMResponse(content="Готово."),
        ]
    )
    result = ExperimentRunner(session, variant).run(
        source,
        experiment_name="safe-replay",
        system_prompt="variant",
        prompt_version="v2",
    )
    after = session.scalar(select(func.count(Event.id)))

    assert result.status == "completed"
    assert after == before
    first_tools = {tool.name for tool in variant.calls[0][1]}
    second_tools = {tool.name for tool in variant.calls[1][1]}
    third_tools = {tool.name for tool in variant.calls[2][1]}
    assert first_tools == {
        "search_items",
        "search_locations",
        "search_categories",
        "search_tags",
    }
    assert "move_item" in second_tools
    assert "move_item" in third_tools


def test_experiment_review_and_summary(session: Session) -> None:
    inventory = InventoryService(session)
    balcony = inventory.create_location("Балкон")
    inventory.create_item("CH341A", location_id=balcony.id)
    source = _source_search_run(session)
    result = ExperimentRunner(
        session,
        ScriptedLLMClient(
            [
                LLMResponse(tool_calls=(ToolCall(id="v1", name="search_items", arguments={"query": "CH341A"}),)),
                LLMResponse(content="Где именно?"),
            ]
        ),
    ).run(
        source,
        experiment_name="strict-v2",
        system_prompt="variant",
        prompt_version="v2",
    )
    service = ExperimentService(session)
    service.set_review(
        result.experiment_run_id,
        choice="variant",
        variant_rating=5,
        comment="лучше",
    )
    summary = service.summaries()[0]

    assert summary.cases == 1
    assert summary.completed == 1
    assert summary.source_average_rating == 4.0
    assert summary.variant_average_rating == 5.0
    assert summary.variant_wins == 1
    assert summary.clarification_rate == 1.0


def test_experiment_summary_separates_provider_configs(session: Session) -> None:
    inventory = InventoryService(session)
    inventory.create_item("CH341A")
    source = _source_search_run(session)
    service = ExperimentService(session)

    common = dict(
        source_run_id=source.id,
        experiment_name="config-compare",
        prompt_version="v2",
        prompt_hash="a" * 64,
        system_prompt="variant",
        llm_provider="groq",
        llm_model="qwen",
        input_messages=[],
        tool_trace=[],
        final_content="ok",
        rounds=1,
        status="completed",
    )
    service.record_run(llm_config={"temperature": 0.0}, **common)
    service.record_run(llm_config={"temperature": 0.6}, **common)

    summaries = [
        summary
        for summary in service.summaries()
        if summary.experiment_name == "config-compare"
    ]
    assert len(summaries) == 2
    assert len({summary.llm_config_hash for summary in summaries}) == 2


def test_replay_marks_suggested_locations_seen_but_not_resolved() -> None:
    state = ToolRunState()

    CapturedEvidenceReplay.observe_capabilities(
        state,
        "suggest_item_locations",
        {"item_id": 1, "limit": 5},
        {
            "ok": True,
            "result": {
                "item_id": 1,
                "stored_current_location_id": None,
                "suggestions": [{"location_id": 17}],
            },
        },
    )

    assert state.seen["location"] == {17}
    assert state.resolved["location"] == set()
