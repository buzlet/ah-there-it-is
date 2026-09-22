"""Probe a configured model/adapter contract without running application logic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.agent.protocol import AgentMessage, LLMClient, ToolDefinition
from ah_there_it_is.config import get_settings


class ProbeExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str | None = None
    required_arguments: list[str] = Field(default_factory=list)
    no_tool_calls: bool = False
    require_text: bool = False


class ModelProbeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    messages: list[AgentMessage] = Field(min_length=1)
    tools: list[ToolDefinition] = Field(default_factory=list)
    expect: ProbeExpectation


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


def run_probe_case(client: LLMClient, case: ModelProbeCase) -> dict[str, Any]:
    response = client.complete(case.messages, case.tools)
    errors: list[str] = []
    expectation = case.expect

    if expectation.no_tool_calls and response.tool_calls:
        errors.append(
            "expected no tool calls, got "
            + ", ".join(call.name for call in response.tool_calls)
        )

    matched = None
    if expectation.tool_name is not None:
        if not response.tool_calls:
            errors.append(f"expected tool {expectation.tool_name!r}, got no tool call")
        else:
            matched = response.tool_calls[0]
            if matched.name != expectation.tool_name:
                errors.append(
                    f"expected first tool {expectation.tool_name!r}, "
                    f"got {matched.name!r}"
                )
            missing_arguments = [
                name
                for name in expectation.required_arguments
                if name not in matched.arguments
            ]
            if missing_arguments:
                errors.append(
                    "missing required tool arguments: "
                    + ", ".join(missing_arguments)
                )

    if expectation.require_text and not response.content.strip():
        errors.append("expected non-empty assistant text")

    advertised = {tool.name for tool in case.tools}
    unknown = [
        call.name for call in response.tool_calls if call.name not in advertised
    ]
    if unknown:
        errors.append(
            "model returned tool names not advertised by the probe: "
            + ", ".join(unknown)
        )

    return {
        "case_id": case.id,
        "passed": not errors,
        "errors": errors,
        "content": response.content,
        "tool_calls": [
            call.model_dump(mode="json") for call in response.tool_calls
        ],
        "metadata": response.metadata,
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
