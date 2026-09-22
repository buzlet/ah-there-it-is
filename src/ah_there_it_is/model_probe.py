"""Probe a configured model/adapter contract without running application logic."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
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


class ProbeExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_names: list[str] | None = None
    required_arguments: dict[str, list[str]] = Field(default_factory=dict)
    argument_equals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    require_text: bool = False


class ProbeToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    content: Any


class ModelProbeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[ToolDefinition] = Field(default_factory=list)
    expect: ProbeExpectation
    tool_results: list[ProbeToolResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _tool_results_require_expected_calls(self) -> "ModelProbeStep":
        expected = self.expect.tool_names
        if self.tool_results and expected is None:
            raise ValueError("tool_results require explicit expected tool_names")
        if expected is not None:
            missing = sorted(
                {result.tool_name for result in self.tool_results} - set(expected)
            )
            if missing:
                raise ValueError(
                    "tool_results reference tools not in expected tool_names: "
                    + ", ".join(missing)
                )
        return self


class ModelProbeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    messages: list[AgentMessage] = Field(min_length=1)
    steps: list[ModelProbeStep] = Field(min_length=1)


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
    step: ModelProbeStep,
) -> list[str]:
    errors: list[str] = []
    expectation = step.expect
    actual_names = [call.name for call in response.tool_calls]

    if expectation.tool_names is not None:
        if Counter(actual_names) != Counter(expectation.tool_names):
            errors.append(
                "expected tool calls "
                f"{expectation.tool_names!r}, got {actual_names!r}"
            )

    if expectation.require_text and not response.content.strip():
        errors.append("expected non-empty assistant text")

    advertised = {tool.name for tool in step.tools}
    unknown = [name for name in actual_names if name not in advertised]
    if unknown:
        errors.append(
            "model returned tool names not advertised by the probe: "
            + ", ".join(unknown)
        )

    calls_by_name: dict[str, list[ToolCall]] = {}
    for call in response.tool_calls:
        calls_by_name.setdefault(call.name, []).append(call)

    for tool_name, required in expectation.required_arguments.items():
        calls = calls_by_name.get(tool_name, [])
        if not calls:
            errors.append(
                f"cannot validate arguments for missing tool {tool_name!r}"
            )
            continue
        for argument in required:
            if argument not in calls[0].arguments:
                errors.append(
                    f"tool {tool_name!r} missing required argument {argument!r}"
                )

    for tool_name, expected_arguments in expectation.argument_equals.items():
        calls = calls_by_name.get(tool_name, [])
        if not calls:
            errors.append(
                f"cannot compare arguments for missing tool {tool_name!r}"
            )
            continue
        for key, expected in expected_arguments.items():
            actual = calls[0].arguments.get(key)
            if actual != expected:
                errors.append(
                    f"tool {tool_name!r} argument {key!r}: "
                    f"expected {expected!r}, got {actual!r}"
                )

    return errors


def _append_turn(
    messages: list[AgentMessage],
    response: LLMResponse,
    step: ModelProbeStep,
) -> list[str]:
    errors: list[str] = []
    messages.append(
        AgentMessage(
            role="assistant",
            content=response.content,
            tool_calls=response.tool_calls,
        )
    )
    calls_by_name: dict[str, list[ToolCall]] = {}
    for call in response.tool_calls:
        calls_by_name.setdefault(call.name, []).append(call)

    for result in step.tool_results:
        matches = calls_by_name.get(result.tool_name, [])
        if len(matches) != 1:
            errors.append(
                f"tool result for {result.tool_name!r} requires exactly one "
                f"matching call, got {len(matches)}"
            )
            continue
        call = matches[0]
        content = (
            result.content
            if isinstance(result.content, str)
            else json.dumps(
                result.content,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )
        messages.append(
            AgentMessage(
                role="tool",
                content=content,
                tool_call_id=call.id,
                tool_name=call.name,
            )
        )
    return errors


def run_probe_case(client: LLMClient, case: ModelProbeCase) -> dict[str, Any]:
    messages = list(case.messages)
    all_errors: list[str] = []
    step_reports: list[dict[str, Any]] = []

    for index, step in enumerate(case.steps, start=1):
        response = client.complete(messages, step.tools)
        errors = _validate_response(response, step)
        errors.extend(_append_turn(messages, response, step))
        all_errors.extend(f"step {index}: {error}" for error in errors)
        step_reports.append(
            {
                "step": index,
                "passed": not errors,
                "errors": errors,
                "content": response.content,
                "tool_calls": [
                    call.model_dump(mode="json") for call in response.tool_calls
                ],
                "metadata": response.metadata,
            }
        )
        if errors:
            break

    return {
        "case_id": case.id,
        "passed": not all_errors and len(step_reports) == len(case.steps),
        "errors": all_errors,
        "steps": step_reports,
    }


def run_probe_suite(
    client: LLMClient,
    suite: ModelProbeSuite,
    *,
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    by_id = {case.id: case for case in suite.cases}
    selected = case_ids or [case.id for case in suite.cases]
    missing = sorted(set(selected) - set(by_id))
    if missing:
        raise ValueError("unknown model probe ids: " + ", ".join(missing))

    cases = [run_probe_case(client, by_id[case_id]) for case_id in selected]
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
