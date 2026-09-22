from __future__ import annotations

from pathlib import Path

from ah_there_it_is.agent.fakes import ScriptedLLMClient
from ah_there_it_is.agent.protocol import LLMResponse, ToolCall
from ah_there_it_is.model_probe import (
    ModelProbeCase,
    ProbeStep,
    ExpectedToolCall,
    load_probe_suite,
    run_probe_case,
    run_probe_suite,
)


ROOT = Path(__file__).resolve().parents[1]
PROBES = ROOT / "eval" / "model-probes-v1.json"


def test_model_probe_pipeline_has_no_application_database_dependency() -> None:
    suite = load_probe_suite(PROBES)
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-1",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="parallel-item",
                        name="search_items",
                        arguments={"query": "CH341A"},
                    ),
                    ToolCall(
                        id="parallel-location",
                        name="search_locations",
                        arguments={"query": "Middle Drawer"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="continue-search",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                        provider_state={"opaque": "preserve-me"},
                    ),
                )
            ),
            LLMResponse(content="It is in the old hardware box."),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="parallel-continue-item",
                        name="search_items",
                        arguments={"query": "CH341A"},
                    ),
                    ToolCall(
                        id="parallel-continue-location",
                        name="search_locations",
                        arguments={"query": "Middle Drawer"},
                    ),
                )
            ),
            LLMResponse(content="Both results were received."),
            LLMResponse(content="OK"),
        ]
    )

    report = run_probe_suite(client, suite)

    assert report["pipeline"] == "model-adapter-contract"
    assert report["summary"] == {"count": 5, "passed": 5, "failed": 0}
    assert client.remaining == 0

    continuation_calls = client.calls[3][0]
    assistant = next(
        message for message in continuation_calls
        if message.role == "assistant" and message.tool_calls
    )
    assert assistant.tool_calls[0].provider_state == {
        "opaque": "preserve-me"
    }
    tool_message = next(
        message for message in continuation_calls
        if message.role == "tool"
    )
    assert tool_message.tool_call_id == "continue-search"
    assert tool_message.tool_name == "search_items"


def test_model_probe_rejects_unadvertised_tool_name() -> None:
    suite = load_probe_suite(PROBES)
    case = suite.cases[0]
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="bad",
                        name="find_items",
                        arguments={"query": "GTX 1070"},
                    ),
                )
            )
        ]
    )

    result = run_probe_case(client, case)

    assert result["passed"] is False
    assert any(
        "no matching call" in error for error in result["errors"]
    )
    assert any(
        "not advertised" in error for error in result["errors"]
    )


def test_model_probe_rejects_missing_required_argument() -> None:
    suite = load_probe_suite(PROBES)
    case = suite.cases[0]
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="bad-args",
                        name="search_items",
                        arguments={},
                    ),
                )
            )
        ]
    )

    result = run_probe_case(client, case)

    assert result["passed"] is False
    assert any(
        "missing required arguments: query" in error
        for error in result["errors"]
    )


def test_model_probe_parallel_expectations_are_order_independent() -> None:
    suite = load_probe_suite(PROBES)
    case = next(
        item for item in suite.cases
        if item.id == "parallel-search-basic"
    )
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="location-first",
                        name="search_locations",
                        arguments={"query": "Middle Drawer"},
                    ),
                    ToolCall(
                        id="item-second",
                        name="search_items",
                        arguments={"query": "CH341A"},
                    ),
                )
            )
        ]
    )

    result = run_probe_case(client, case)

    assert result["passed"] is True


def test_model_probe_stops_after_failed_step() -> None:
    case = ModelProbeCase(
        id="stop",
        messages=[
            {"role": "user", "content": "test"},
        ],
        tools=[],
        steps=[
            ProbeStep(
                expect_tool_calls=[
                    ExpectedToolCall(name="search_items")
                ]
            ),
            ProbeStep(no_tool_calls=True, require_text=True),
        ],
    )
    client = ScriptedLLMClient([LLMResponse(content="wrong")])

    result = run_probe_case(client, case)

    assert result["passed"] is False
    assert len(result["steps"]) == 1
    assert client.remaining == 0
