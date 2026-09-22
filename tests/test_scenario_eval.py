from __future__ import annotations

import json
from pathlib import Path

import pytest

from ah_there_it_is.agent.protocol import AgentMessage, ToolDefinition
from ah_there_it_is.agent.scenario_mock import (
    ScenarioCase,
    ScenarioLLMClient,
    ScenarioMismatchError,
    ScenarioStep,
    ScenarioToolCall,
    load_scenario_suite,
)
from ah_there_it_is.scenario_eval import run_suite


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "eval" / "scenarios-v1.json"
CORPUS = ROOT / "eval" / "corpus-v1.json"


def test_scenario_mock_resolves_real_tool_result_reference() -> None:
    client = ScenarioLLMClient(
        ScenarioCase(
            case_id="reference",
            steps=[
                ScenarioStep(
                    expect_tools=["get_item"],
                    tool_calls=[
                        ScenarioToolCall(
                            name="get_item",
                            arguments={"id": "${tool:search_items:result.0.id}"},
                        )
                    ],
                )
            ],
        )
    )
    messages = [
        AgentMessage(
            role="tool",
            tool_call_id="search-1",
            tool_name="search_items",
            content=json.dumps(
                {"ok": True, "result": [{"id": 42, "name": "thing"}]}
            ),
        )
    ]
    tools = [
        ToolDefinition(
            name="get_item",
            description="read",
            input_schema={"type": "object"},
        )
    ]

    response = client.complete(messages, tools)

    assert response.tool_calls[0].arguments == {"id": 42}
    client.assert_exhausted()


def test_scenario_mock_rejects_unavailable_planned_tool() -> None:
    client = ScenarioLLMClient(
        ScenarioCase(
            case_id="unavailable",
            steps=[
                ScenarioStep(
                    tool_calls=[
                        ScenarioToolCall(name="move_item", arguments={})
                    ]
                )
            ],
        )
    )

    with pytest.raises(ScenarioMismatchError, match="unavailable"):
        client.complete([], [])


def test_scenario_suite_matches_corpus_and_core_cases_pass() -> None:
    suite = load_scenario_suite(SCENARIOS)
    assert suite.version == "inventory-scenarios-v1"

    report = run_suite(
        corpus_path=CORPUS,
        scenarios_path=SCENARIOS,
    )

    assert report["pipeline"] == "application-scenario-mock"
    assert report["summary"] == {
        "count": 5,
        "completed": 5,
        "failed": 0,
        "checks_passed": 5,
    }
    assert [case["case_id"] for case in report["cases"]] == [
        "find-01",
        "move-01",
        "create-01",
        "ambiguity-01",
        "history-01",
    ]


def test_scenario_suite_can_select_one_case() -> None:
    report = run_suite(
        corpus_path=CORPUS,
        scenarios_path=SCENARIOS,
        case_ids=["move-01"],
    )
    assert report["summary"]["count"] == 1
    assert report["cases"][0]["case_id"] == "move-01"
