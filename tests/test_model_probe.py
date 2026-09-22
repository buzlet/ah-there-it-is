from __future__ import annotations

from pathlib import Path

from ah_there_it_is.agent.fakes import ScriptedLLMClient
from ah_there_it_is.agent.protocol import LLMResponse, ToolCall
from ah_there_it_is.model_probe import (
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
                        id="search-basic",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                    ),
                )
            ),
            LLMResponse(content="OK"),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search-continuation",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                        provider_state={"opaque": "preserved"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="get-continuation",
                        name="get_item",
                        arguments={"id": 17},
                    ),
                )
            ),
            LLMResponse(content="GTX 1070 is on the balcony shelf."),
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
                        arguments={"query": "Средний ящик"},
                    ),
                )
            ),
        ]
    )

    report = run_probe_suite(client, suite)

    assert report["pipeline"] == "model-adapter-contract"
    assert report["summary"] == {"count": 4, "passed": 4, "failed": 0}
    assert client.remaining == 0

    continuation_calls = client.calls[3][0]
    assistant = next(
        message
        for message in continuation_calls
        if message.role == "assistant" and message.tool_calls
    )
    assert assistant.tool_calls[0].provider_state == {"opaque": "preserved"}
    tool_result = next(
        message
        for message in continuation_calls
        if message.role == "tool" and message.tool_name == "search_items"
    )
    assert tool_result.tool_call_id == "search-continuation"


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
    assert any("expected tool calls" in error for error in result["errors"])
    assert any("not advertised" in error for error in result["errors"])


def test_model_probe_rejects_wrong_continuation_id() -> None:
    suite = load_probe_suite(PROBES)
    case = next(
        case for case in suite.cases if case.id == "tool-result-continuation"
    )
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="search",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="get",
                        name="get_item",
                        arguments={"id": 999},
                    ),
                )
            ),
        ]
    )

    result = run_probe_case(client, case)

    assert result["passed"] is False
    assert any(
        "expected 17, got 999" in error
        for error in result["errors"]
    )
    assert len(result["steps"]) == 2


def test_model_probe_accepts_parallel_calls_in_any_order() -> None:
    suite = load_probe_suite(PROBES)
    case = next(case for case in suite.cases if case.id == "parallel-tool-calls")
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="location",
                        name="search_locations",
                        arguments={"query": "Средний ящик"},
                    ),
                    ToolCall(
                        id="item",
                        name="search_items",
                        arguments={"query": "CH341A"},
                    ),
                )
            )
        ]
    )

    result = run_probe_case(client, case)

    assert result["passed"] is True
