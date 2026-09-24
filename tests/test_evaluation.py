from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import AgentLoopLimitError
from ah_there_it_is.db.models import AgentFeedback, AgentRunLog
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService


def test_agent_run_log_captures_prompt_input_and_tool_trace(session: Session) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(ToolCall(id="1", name="search_items", arguments={"query": "x"}),)
            ),
            LLMResponse(content="Не найдено."),
        ]
    )
    prompt = "custom inventory prompt"

    result = AgentRunner(
        session,
        llm,
        system_prompt=prompt,
        prompt_version="experiment-a",
    ).run("Где x?")

    run = EvaluationService(session).get_run(result.run_id)
    assert run.status == "completed"
    assert run.prompt_version == "experiment-a"
    assert run.prompt_hash == hashlib.sha256(prompt.encode()).hexdigest()
    assert run.llm_provider == "test"
    assert run.llm_model == "scripted-v1"
    assert run.input_messages[-1]["content"] == "Где x?"
    assert run.tool_trace[0]["tool_results"][0]["tool_name"] == "search_items"
    assert run.final_content == "Не найдено."


def test_feedback_is_upserted_and_summarized_by_exact_variant(session: Session) -> None:
    runner = AgentRunner(
        session,
        ScriptedLLMClient([LLMResponse(content="Ответ")]),
        system_prompt="prompt one",
        prompt_version="v1",
    )
    first = runner.run("A")
    evaluation = EvaluationService(session)
    evaluation.set_feedback(first.run_id, rating=2, comment="плохо")
    updated = evaluation.set_feedback(first.run_id, rating=5, comment="после проверки")

    assert updated.rating == 5
    assert updated.comment == "после проверки"
    summaries = evaluation.summaries()
    assert len(summaries) == 1
    assert summaries[0].runs == 1
    assert summaries[0].rated_runs == 1
    assert summaries[0].average_rating == 5.0


def test_evaluation_run_pages_and_sql_summaries_are_bounded(session: Session) -> None:
    conversation_id = ConversationService(session).create().id
    runs = [
        AgentRunLog(
            conversation_id=conversation_id,
            prompt_version="bulk-v1",
            prompt_hash="a" * 64,
            system_prompt="bulk",
            llm_provider="test",
            llm_model="bulk",
            llm_config=(
                {"temperature": 0, "nested": {"x": 1}}
                if index % 2
                else {"nested": {"x": 1}, "temperature": 0}
            ),
            input_messages=[{"heavy": "x" * 100}],
            tool_trace=[{"heavy": "y" * 100}],
            mutation_receipts=[],
            final_content="done",
            rounds=1,
            status="completed",
        )
        for index in range(125)
    ]
    session.add_all(runs)
    session.flush()
    session.add_all(
        AgentFeedback(run=run, rating=(index % 5) + 1)
        for index, run in enumerate(runs[:100])
    )
    session.commit()
    session.expunge_all()

    service = EvaluationService(session)
    first = service.run_page(page=1)
    third = service.run_page(page=3)
    assert len(first.runs) == 50 and first.total == 125
    assert first.has_previous is False and first.has_next is True
    assert len(third.runs) == 25 and third.has_previous is True
    assert third.has_next is False
    assert first.runs[0].id > first.runs[-1].id > third.runs[-1].id

    session.expunge_all()
    loaded_runs: list[AgentRunLog] = []
    event.listen(
        session,
        "loaded_as_persistent",
        lambda _session, instance: loaded_runs.append(instance)
        if isinstance(instance, AgentRunLog)
        else None,
    )
    summaries = service.summaries()
    assert loaded_runs == []
    assert len(summaries) == 1
    assert summaries[0].runs == 125
    assert summaries[0].rated_runs == 100
    assert summaries[0].average_rating == 3.0

    for page, page_size in ((0, 50), (1, 0), (1, 101)):
        with pytest.raises(ValueError):
            service.run_page(page=page, page_size=page_size)


def test_evaluation_summary_separates_provider_configs(session: Session) -> None:
    evaluation = EvaluationService(session)
    first = AgentRunner(
        session,
        ScriptedLLMClient([LLMResponse(content="A")]),
        system_prompt="same prompt",
        prompt_version="same",
    ).run("one")
    second = AgentRunner(
        session,
        ScriptedLLMClient([LLMResponse(content="B")]),
        system_prompt="same prompt",
        prompt_version="same",
    ).run("two")

    first_run = evaluation.get_run(first.run_id)
    second_run = evaluation.get_run(second.run_id)
    first_run.llm_config = {"temperature": 0.0, "nested": {"x": 1}}
    second_run.llm_config = {"nested": {"x": 1}, "temperature": 0.6}
    session.commit()

    summaries = evaluation.summaries()
    assert len(summaries) == 2
    assert {summary.llm_config_hash for summary in summaries}
    assert len({summary.llm_config_hash for summary in summaries}) == 2
    assert {summary.llm_config["temperature"] for summary in summaries} == {0.0, 0.6}


def test_failed_agent_run_is_logged_for_evaluation(session: Session) -> None:
    llm = ScriptedLLMClient(
        [LLMResponse(tool_calls=(ToolCall(id="1", name="search_items", arguments={"query": "x"}),))]
    )

    with pytest.raises(AgentLoopLimitError):
        AgentRunner(session, llm, max_rounds=1).run("ищи x")

    runs = EvaluationService(session).recent_runs()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "AgentLoopLimitError" in (runs[0].error or "")
    assert runs[0].tool_trace


def test_failed_agent_turn_rolls_back_prior_inventory_mutation(session: Session) -> None:
    from sqlalchemy import func, select

    from ah_there_it_is.db.models import Event
    from ah_there_it_is.services.inventory import InventoryService

    inventory = InventoryService(session)
    original = inventory.create_location("Original")
    target = inventory.create_location("Target")
    item = inventory.create_item("Atomic Widget", location_id=original.id)
    events_before = int(session.scalar(select(func.count(Event.id))) or 0)

    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-item",
                        name="search_items",
                        arguments={"query": "Atomic Widget"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-location",
                        name="search_locations",
                        arguments={"query": "Target"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="move",
                        name="move_item",
                        arguments={"item_id": item.id, "location_id": target.id},
                    ),
                )
            ),
        ]
    )

    with pytest.raises(AgentLoopLimitError):
        AgentRunner(session, llm, max_rounds=3).run(
            "Перемести Atomic Widget в Target"
        )

    session.expire_all()
    assert inventory.get_item(item.id).current_location_id == original.id
    assert int(session.scalar(select(func.count(Event.id))) or 0) == events_before

    runs = EvaluationService(session).recent_runs()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "AgentLoopLimitError" in (runs[0].error or "")
    assert any(
        result["tool_name"] == "move_item" and result["result"]["ok"] is True
        for round_trace in runs[0].tool_trace
        for result in round_trace["tool_results"]
    )


def test_failed_agent_turn_rolls_back_created_item(session: Session) -> None:
    from sqlalchemy import func, select

    from ah_there_it_is.db.models import Event
    from ah_there_it_is.services.inventory import InventoryService
    from ah_there_it_is.services.search import SearchService

    inventory = InventoryService(session)
    target = inventory.create_location("Create Target")
    events_before = int(session.scalar(select(func.count(Event.id))) or 0)

    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-new",
                        name="search_items",
                        arguments={"query": "Transient Widget"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-target",
                        name="search_locations",
                        arguments={"query": "Create Target"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="create",
                        name="create_item",
                        arguments={
                            "name": "Transient Widget",
                            "location_id": target.id,
                        },
                    ),
                )
            ),
        ]
    )

    with pytest.raises(AgentLoopLimitError):
        AgentRunner(session, llm, max_rounds=3).run(
            "Добавь Transient Widget в Create Target"
        )

    session.expire_all()
    assert SearchService(session).search_items("Transient Widget") == []
    assert int(session.scalar(select(func.count(Event.id))) or 0) == events_before

    run = EvaluationService(session).recent_runs()[0]
    assert run.status == "failed"
    assert any(
        result["tool_name"] == "create_item" and result["result"]["ok"] is True
        for round_trace in run.tool_trace
        for result in round_trace["tool_results"]
    )


def test_failed_agent_turn_rolls_back_item_update(session: Session) -> None:
    from sqlalchemy import func, select

    from ah_there_it_is.db.models import Event
    from ah_there_it_is.services.inventory import InventoryService

    inventory = InventoryService(session)
    item = inventory.create_item("Update Atomic Widget")
    events_before = int(session.scalar(select(func.count(Event.id))) or 0)

    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-update",
                        name="search_items",
                        arguments={"query": "Update Atomic Widget"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="update",
                        name="update_item",
                        arguments={"item_id": item.id, "state": "broken"},
                    ),
                )
            ),
        ]
    )

    with pytest.raises(AgentLoopLimitError):
        AgentRunner(session, llm, max_rounds=2).run(
            "Update Atomic Widget теперь неисправен"
        )

    session.expire_all()
    assert inventory.get_item(item.id).state == "unknown"
    assert int(session.scalar(select(func.count(Event.id))) or 0) == events_before

    run = EvaluationService(session).recent_runs()[0]
    assert run.status == "failed"
    assert any(
        result["tool_name"] == "update_item" and result["result"]["ok"] is True
        for round_trace in run.tool_trace
        for result in round_trace["tool_results"]
    )


def test_failed_agent_turn_keeps_diagnostics_but_no_conversation_message(
    session: Session,
) -> None:
    from ah_there_it_is.services.conversations import ConversationService

    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-only",
                        name="search_items",
                        arguments={"query": "nothing"},
                    ),
                )
            )
        ]
    )

    with pytest.raises(AgentLoopLimitError):
        AgentRunner(session, llm, max_rounds=1).run("Найди nothing")

    run = EvaluationService(session).recent_runs()[0]
    messages = ConversationService(session).message_window(run.conversation_id).messages
    assert messages == []
    assert run.user_message_id is None
    assert run.assistant_message_id is None
    assert run.input_messages[-1]["content"] == "Найди nothing"
    assert run.mutation_receipts == []
