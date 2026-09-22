from __future__ import annotations

import json
from pathlib import Path

import pytest

from ah_there_it_is.agent.protocol import AgentMessage, ToolDefinition
from ah_there_it_is.agent.scenario_mock import (
    ScenarioCase,
    ScenarioLLMClient,
    ScenarioMismatchError,
    ScenarioResultExpectation,
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


def test_scenario_mock_asserts_previous_result_cardinality() -> None:
    client = ScenarioLLMClient(
        ScenarioCase(
            case_id="ambiguity",
            steps=[
                ScenarioStep(
                    expect_results=[
                        ScenarioResultExpectation(
                            tool_name="search_items",
                            min_items=2,
                        )
                    ],
                    final="clarify",
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
                {"ok": True, "result": [{"id": 1}]}
            ),
        )
    ]

    with pytest.raises(ScenarioMismatchError, match="at least 2"):
        client.complete(messages, [])


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
    assert report["summary"]["count"] == len(suite.cases)
    assert report["summary"]["completed"] == len(suite.cases)
    assert report["summary"]["failed"] == 0
    assert {
        "find-01",
        "move-01",
        "create-01",
        "ambiguity-01",
        "history-01",
        "ambiguity-04",
        "update-03",
        "safety-03",
    }.issubset({case["case_id"] for case in report["cases"]})


def test_scenario_failure_report_preserves_partial_tool_trace(tmp_path) -> None:
    suite_path = tmp_path / "scenarios.json"
    suite_path.write_text(
        json.dumps(
            {
                "version": "failure-trace-test",
                "corpus_version": "inventory-corpus-v1",
                "cases": [
                    {
                        "case_id": "find-01",
                        "steps": [
                            {
                                "tool_calls": [
                                    {
                                        "name": "search_items",
                                        "arguments": {"query": "GTX 1070"},
                                    }
                                ]
                            },
                            {
                                "tool_calls": [
                                    {
                                        "name": "create_item",
                                        "arguments": {"name": "should-not-create"},
                                    }
                                ]
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_suite(
        corpus_path=CORPUS,
        scenarios_path=suite_path,
    )

    case = report["cases"][0]
    assert case["status"] == "failed"
    assert "create_item" in case["error"]
    assert case["turns"]
    assert case["turns"][0]["status"] == "failed"
    assert case["turns"][0]["tool_trace"][0]["assistant"]["tool_calls"][0]["name"] == (
        "search_items"
    )


def test_scenario_suite_can_select_one_case() -> None:
    report = run_suite(
        corpus_path=CORPUS,
        scenarios_path=SCENARIOS,
        case_ids=["move-01"],
    )
    assert report["summary"]["count"] == 1
    assert report["cases"][0]["case_id"] == "move-01"
