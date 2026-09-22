"""Probe a configured model/adapter contract without application business logic."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClient,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)
from ah_there_it_is.config import get_settings


class ExpectedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    required_arguments: list[str] = Field(default_factory=list)


class SyntheticToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    payload: Any


class ProbeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expect_tool_calls: list[ExpectedToolCall] = Field(default_factory=list)
    no_tool_calls: bool = False
    require_text: bool = False
    allow_extra_tool_calls: bool = False
    tool_results: list[SyntheticToolResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_contract(self) -> "ProbeStep":
        if self.no_tool_calls and self.expect_tool_calls:
            raise ValueError(
                "no_tool_calls cannot be combined with expect_tool_calls"
            )
        expected_names = [call.name for call in self.expect_tool_calls]
        if len(expected_names) != len(set(expected_names)):
            raise ValueError("expected tool names must be unique within a step")
        result_names = [result.tool_name for result in self.tool_results]
        if len(result_names) != len(set(result_names)):
            raise ValueError("synthetic tool-result names must be unique")
        unknown_results = sorted(set(result_names) - set(expected_names))
        if unknown_results:
            raise ValueError(
                "synthetic tool results require matching expected tool calls: "
                + ", ".join(unknown_results)
            )
        return self


class ModelProbeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    messages: list[AgentMessage] = Field(min_length=1)
    tools: list[ToolDefinition] = Field(default_factory=list)
    steps: list[ProbeStep] = Field(min_length=1)


class ModelProbeSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    cases: list[ModelProbeCase]


def load_probe_suite(path: str | Path) -> ModelProbeSuite:
    suite = ModelProbeSuite.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
    ids = [case.id for case in suite.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("model probe ids must be unique")
    return suite


def _validate_response(
    response: LLMResponse,
    tools: list[ToolDefinition],
    step: ProbeStep,
) -> list[str]:
    errors: list[str] = []
    advertised = {tool.name for tool in tools}

    unknown = [
        call.name for call in response.tool_calls if call.name not in advertised
    ]
    if unknown:
        errors.append(
            "model returned tool names not advertised by the probe: "
            + ", ".join(unknown)
        )

    if step.no_tool_calls and response.tool_calls:
        errors.append(
            "expected no tool calls, got "
            + ", ".join(call.name for call in response.tool_calls)
        )

    matched_indexes: set[int] = set()
    for expected in step.expect_tool_calls:
        match_index = next(
            (
                index
                for index, call in enumerate(response.tool_calls)
                if index not in matched_indexes and call.name == expected.name
            ),
            None,
        )
        if match_index is None:
            errors.append(f"expected tool {expected.name!r}, got no matching call")
            continue
        matched_indexes.add(match_index)
        call = response.tool_calls[match_index]
        missing = [
            name for name in expected.required_arguments
            if name not in call.arguments
        ]
        if missing:
            errors.append(
                f"tool {expected.name!r} missing required arguments: "
                + ", ".join(missing)
            )

    if (
        step.expect_tool_calls
        and not step.allow_extra_tool_calls
        and len(response.tool_calls) != len(step.expect_tool_calls)
    ):
        errors.append(
            f"expected exactly {len(step.expect_tool_calls)} tool call(s), "
            f"got {len(response.tool_calls)}"
        )

    if step.require_text and not response.content.strip():
        errors.append("expected non-empty assistant text")

    return errors


def _tool_result_messages(
    response: LLMResponse,
    step: ProbeStep,
) -> list[AgentMessage]:
    results_by_name = {result.tool_name: result for result in step.tool_results}
    messages: list[AgentMessage] = []
    for call in response.tool_calls:
        result = results_by_name.get(call.name)
        if result is None:
            continue
        messages.append(
            AgentMessage(
                role="tool",
                content=json.dumps(
                    result.payload,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                tool_call_id=call.id,
                tool_name=call.name,
            )
        )
    return messages


def run_probe_case(
    client: LLMClient,
    case: ModelProbeCase,
    *,
    before_request: Callable[[], None] | None = None,
) -> dict[str, Any]:
    messages = list(case.messages)
    step_reports: list[dict[str, Any]] = []
    case_errors: list[str] = []

    for step_number, step in enumerate(case.steps, start=1):
        if before_request is not None:
            before_request()
        response = client.complete(messages, case.tools)
        errors = _validate_response(response, case.tools, step)
        step_reports.append(
            {
                "step": step_number,
                "passed": not errors,
                "errors": errors,
                "content": response.content,
                "tool_calls": [
                    call.model_dump(mode="json")
                    for call in response.tool_calls
                ],
                "metadata": response.metadata,
            }
        )
        if errors:
            case_errors.extend(
                f"step {step_number}: {error}" for error in errors
            )
            break

        # Preserve the exact provider-neutral ToolCall returned by the adapter.
        # Provider-only opaque state remains attached in memory and can be
        # round-tripped by provider adapters without leaking into JSON reports.
        messages.append(
            AgentMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            )
        )
        messages.extend(_tool_result_messages(response, step))

    return {
        "case_id": case.id,
        "passed": not case_errors and len(step_reports) == len(case.steps),
        "errors": case_errors,
        "steps": step_reports,
    }


def run_probe_suite(
    client: LLMClient,
    suite: ModelProbeSuite,
    *,
    case_ids: list[str] | None = None,
    delay_seconds: float = 0.0,
) -> dict[str, Any]:
    by_id = {case.id: case for case in suite.cases}
    selected = case_ids or [case.id for case in suite.cases]
    missing = sorted(set(selected) - set(by_id))
    if missing:
        raise ValueError("unknown model probe ids: " + ", ".join(missing))

    request_count = 0

    def before_request() -> None:
        nonlocal request_count
        if request_count and delay_seconds > 0:
            time.sleep(delay_seconds)
        request_count += 1

    cases = [
        run_probe_case(
            client,
            by_id[case_id],
            before_request=before_request,
        )
        for case_id in selected
    ]
    return {
        "pipeline": "model-adapter-contract",
        "suite_version": suite.version,
        "provider": client.info.model_dump(mode="json"),
        "cases": cases,
        "summary": {
            "count": len(cases),
            "passed": sum(case["passed"] for case in cases),
            "failed": sum(not case["passed"] for case in cases),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="eval/model-probes-v1.json")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--output", default="model-probe.json")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    args = parser.parse_args()

    settings = get_settings()
    if settings.llm_provider == "heuristic":
        raise SystemExit(
            "model-probe requires a real configured provider; "
            "application tests use scenario-eval instead"
        )

    client = build_llm_factory(settings)()
    try:
        report = run_probe_suite(
            client,
            load_probe_suite(args.suite),
            case_ids=args.case_ids,
            delay_seconds=args.delay_seconds,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if report["summary"]["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
