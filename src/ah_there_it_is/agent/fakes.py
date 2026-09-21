"""Offline LLM doubles used by tests and sandbox development."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ah_there_it_is.agent.protocol import AgentMessage, LLMResponse, ToolDefinition


class ScriptedLLMClient:
    """Return a predetermined sequence of model turns and record requests.

    This is intentionally not a natural-language model. It lets the complete
    agent/tool protocol be exercised offline and deterministically.
    """

    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[tuple[AgentMessage, ...], tuple[ToolDefinition, ...]]] = []

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        self.calls.append((tuple(messages), tuple(tools)))
        if not self._responses:
            raise RuntimeError("scripted LLM has no response left")
        return self._responses.pop(0)

    @property
    def remaining(self) -> int:
        return len(self._responses)
