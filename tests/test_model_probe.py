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
                        id="probe-1",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                    ),
                )
            ),
            LLMResponse(content="OK"),
        ]
    )

    report = run_probe_suite(client, suite)

    assert report["pipeline"] == "model-adapter-contract"
    assert report["summary"] == {"count": 2, "passed": 2, "failed": 0}
    assert client.remaining == 0


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
    assert any("expected first tool" in error for error in result["errors"])
    assert any("not advertised" in error for error in result["errors"])


def test_model_probe_paces_cases(monkeypatch) -> None:
    suite = load_probe_suite(PROBES)
    client = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="probe-1",
                        name="search_items",
                        arguments={"query": "GTX 1070"},
                    ),
                )
            ),
            LLMResponse(content="OK"),
        ]
    )
    sleeps: list[float] = []
    import ah_there_it_is.model_probe as probe_module
    monkeypatch.setattr(probe_module.time, "sleep", sleeps.append)

    report = run_probe_suite(client, suite, delay_seconds=3.2)

    assert report["summary"]["passed"] == 2
    assert sleeps == [3.2]
