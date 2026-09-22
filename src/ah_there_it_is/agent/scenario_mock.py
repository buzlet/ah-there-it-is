"""Deterministic scenario-driven LLM double for application tests."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClientInfo,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)


_REF = re.compile(r"^\$\{tool:([^:]+):(.+)\}$")


class ScenarioMismatchError(AssertionError):
    """The application diverged from a deterministic scenario contract."""


class ScenarioToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ScenarioResultExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    path: str = "result"
    min_items: int | None = Field(default=None, ge=0)
    max_items: int | None = Field(default=None, ge=0)
    equals: Any | None = None


class ScenarioStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expect_tools: list[str] = Field(default_factory=list)
    forbid_tools: list[str] = Field(default_factory=list)
    expect_results: list[ScenarioResultExpectation] = Field(default_factory=list)
    tool_calls: list[ScenarioToolCall] = Field(default_factory=list)
    final: str | None = None

    @model_validator(mode="after")
    def _exactly_one_output(self) -> "ScenarioStep":
        if bool(self.tool_calls) == (self.final is not None):
            raise ValueError("scenario step requires exactly one of tool_calls or final")
        return self


class ScenarioCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    steps: list[ScenarioStep] = Field(min_length=1)


class ScenarioSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    corpus_version: str
    cases: list[ScenarioCase]


def load_scenario_suite(path: str | Path) -> ScenarioSuite:
    suite = ScenarioSuite.model_validate(
        json.loads(Path(path).read_text(encoding="utf-8"))
    )
    ids = [case.case_id for case in suite.cases]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario case ids must be unique")
    return suite


class ScenarioLLMClient:
    """Execute a declared model transcript while the real application executes tools.

    Tool arguments may reference the latest real result of a prior tool call:

        ${tool:search_items:result.0.id}

    References are resolved from AgentMessage(role="tool") messages emitted by
    AgentRunner. Thus search/retrieval regressions are not hidden by hard-coded
    fixture IDs.
    """

    def __init__(self, scenario: ScenarioCase) -> None:
        self.scenario = scenario
        self._index = 0
        self.calls: list[tuple[tuple[AgentMessage, ...], tuple[ToolDefinition, ...]]] = []

    @property
    def info(self) -> LLMClientInfo:
        return LLMClientInfo(
            provider="scenario-mock",
            model="scenario-v1",
            config={"case_id": self.scenario.case_id},
        )

    @property
    def remaining(self) -> int:
        return len(self.scenario.steps) - self._index

    def assert_exhausted(self) -> None:
        if self.remaining:
            raise ScenarioMismatchError(
                f"scenario {self.scenario.case_id!r} has "
                f"{self.remaining} unconsumed step(s)"
            )

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append((tuple(messages), tuple(tools)))
        if self._index >= len(self.scenario.steps):
            raise ScenarioMismatchError(
                f"scenario {self.scenario.case_id!r} has no step "
                f"for model call {self._index + 1}"
            )

        self._assert_trailing_tool_results_ok(messages)
        step = self.scenario.steps[self._index]
        self._assert_expected_results(step, messages)
        self._index += 1
        available = {tool.name for tool in tools}
        missing = sorted(set(step.expect_tools) - available)
        if missing:
            raise ScenarioMismatchError(
                f"scenario {self.scenario.case_id!r} step {self._index}: "
                f"application did not expose expected tools {missing}; "
                f"available={sorted(available)}"
            )
        forbidden = sorted(set(step.forbid_tools).intersection(available))
        if forbidden:
            raise ScenarioMismatchError(
                f"scenario {self.scenario.case_id!r} step {self._index}: "
                f"application exposed forbidden tools {forbidden}; "
                f"available={sorted(available)}"
            )

        if step.final is not None:
            return LLMResponse(
                content=step.final,
                metadata={
                    "scenario_case_id": self.scenario.case_id,
                    "scenario_step": self._index,
                },
            )

        calls: list[ToolCall] = []
        for offset, planned in enumerate(step.tool_calls, start=1):
            if planned.name not in available:
                raise ScenarioMismatchError(
                    f"scenario {self.scenario.case_id!r} step {self._index}: "
                    f"planned tool {planned.name!r} is unavailable; "
                    f"available={sorted(available)}"
                )
            calls.append(
                ToolCall(
                    id=f"scenario-{self._index}-{offset}",
                    name=planned.name,
                    arguments=self._resolve(planned.arguments, messages),
                )
            )
        return LLMResponse(
            tool_calls=tuple(calls),
            metadata={
                "scenario_case_id": self.scenario.case_id,
                "scenario_step": self._index,
            },
        )

    def _assert_expected_results(
        self,
        step: ScenarioStep,
        messages: Sequence[AgentMessage],
    ) -> None:
        for expected in step.expect_results:
            payload = self._latest_tool_payload(messages, expected.tool_name)
            current = self._path_value(
                payload,
                expected.path,
                label=f"tool {expected.tool_name!r}",
            )
            if expected.min_items is not None:
                if not hasattr(current, "__len__") or len(current) < expected.min_items:
                    raise ScenarioMismatchError(
                        f"scenario {self.scenario.case_id!r}: "
                        f"{expected.tool_name}.{expected.path} expected at least "
                        f"{expected.min_items} item(s), got {current!r}"
                    )
            if expected.max_items is not None:
                if not hasattr(current, "__len__") or len(current) > expected.max_items:
                    raise ScenarioMismatchError(
                        f"scenario {self.scenario.case_id!r}: "
                        f"{expected.tool_name}.{expected.path} expected at most "
                        f"{expected.max_items} item(s), got {current!r}"
                    )
            if expected.equals is not None and current != expected.equals:
                raise ScenarioMismatchError(
                    f"scenario {self.scenario.case_id!r}: "
                    f"{expected.tool_name}.{expected.path} expected "
                    f"{expected.equals!r}, got {current!r}"
                )

    def _path_value(self, payload: Any, path: str, *, label: str) -> Any:
        current = payload
        if not path:
            return current
        for token in path.split("."):
            try:
                if isinstance(current, list):
                    current = current[int(token)]
                elif isinstance(current, dict):
                    current = current[token]
                else:
                    raise TypeError(type(current).__name__)
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise ScenarioMismatchError(
                    f"scenario {self.scenario.case_id!r}: "
                    f"cannot resolve {label}.{path} at token {token!r}"
                ) from exc
        return current

    def _assert_trailing_tool_results_ok(
        self,
        messages: Sequence[AgentMessage],
    ) -> None:
        for message in reversed(messages):
            if message.role != "tool":
                break
            try:
                payload = json.loads(message.content)
            except json.JSONDecodeError as exc:
                raise ScenarioMismatchError(
                    f"tool {message.tool_name!r} returned non-JSON content"
                ) from exc
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise ScenarioMismatchError(
                    f"scenario {self.scenario.case_id!r}: "
                    f"tool {message.tool_name!r} failed: {payload!r}"
                )

    def _resolve(
        self,
        value: Any,
        messages: Sequence[AgentMessage],
    ) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve(item, messages) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve(item, messages) for item in value]
        if not isinstance(value, str):
            return value

        match = _REF.fullmatch(value)
        if match is None:
            return value
        tool_name, path = match.groups()
        payload = self._latest_tool_payload(messages, tool_name)
        return self._path_value(payload, path, label=value)

    def _latest_tool_payload(
        self,
        messages: Sequence[AgentMessage],
        tool_name: str,
    ) -> Any:
        for message in reversed(messages):
            if message.role != "tool" or message.tool_name != tool_name:
                continue
            try:
                return json.loads(message.content)
            except json.JSONDecodeError as exc:
                raise ScenarioMismatchError(
                    f"tool {tool_name!r} returned non-JSON content"
                ) from exc
        raise ScenarioMismatchError(
            f"scenario {self.scenario.case_id!r}: no prior result "
            f"for tool {tool_name!r}"
        )
