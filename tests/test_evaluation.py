from __future__ import annotations

import hashlib

import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import AgentLoopLimitError
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
