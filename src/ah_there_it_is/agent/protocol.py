"""Provider-neutral message, tool, and LLM client protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


Role = Literal["system", "user", "assistant", "tool"]


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Provider-only opaque state needed inside the current tool loop (for example,
    # Gemini thought signatures). It must never leak into persisted traces.
    provider_state: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)


class AgentMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    input_schema: dict[str, Any]


class LLMClientInfo(BaseModel):
    """Stable metadata stored with every agent run for later evaluation."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    config: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMClient(Protocol):
    """Small adapter boundary implemented by real and fake model providers."""

    @property
    def info(self) -> LLMClientInfo: ...

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse: ...
