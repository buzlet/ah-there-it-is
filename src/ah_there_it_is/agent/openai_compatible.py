"""Minimal synchronous OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ah_there_it_is.agent.errors import ProviderProtocolError, ProviderRequestError
from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClientInfo,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    model: str
    api_key: str | None = None
    provider_name: str = "openai-compatible"
    timeout_seconds: float = 60.0
    temperature: float | None = None
    extra_body: dict[str, Any] | None = None


class OpenAICompatibleLLMClient:
    """Call a provider implementing the OpenAI chat-completions tool format.

    No provider SDK is required. This keeps the adapter small and makes the same
    boundary usable for hosted providers and local OpenAI-compatible servers.
    """

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        if not config.base_url.strip():
            raise ValueError("base_url must not be empty")
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self.config = config

    @property
    def info(self) -> LLMClientInfo:
        logged_config: dict[str, Any] = {
            "base_url": self.config.base_url.rstrip("/"),
            "timeout_seconds": self.config.timeout_seconds,
        }
        if self.config.temperature is not None:
            logged_config["temperature"] = self.config.temperature
        if self.config.extra_body:
            logged_config["extra_body"] = dict(self.config.extra_body)
        return LLMClientInfo(
            provider=self.config.provider_name,
            model=self.config.model,
            config=logged_config,
        )

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [self._message_payload(message) for message in messages],
            "stream": False,
        }
        if tools:
            body["tools"] = [self._tool_payload(tool) for tool in tools]
            body["tool_choice"] = "auto"
        if self.config.temperature is not None:
            body["temperature"] = self.config.temperature
        if self.config.extra_body:
            protected = {"model", "messages", "tools", "stream"}
            collision = protected.intersection(self.config.extra_body)
            if collision:
                raise ValueError(
                    "extra_body cannot override protected keys: "
                    + ", ".join(sorted(collision))
                )
            body.update(self.config.extra_body)

        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = Request(self._endpoint(), data=payload, headers=headers, method="POST")

        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:4000]
            raise ProviderRequestError(
                f"provider HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise ProviderRequestError(f"provider request failed: {exc.reason}") from exc

        try:
            data = json.loads(raw)
            choice = data["choices"][0]
            message = choice["message"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderProtocolError("invalid chat-completions response") from exc

        tool_calls: list[ToolCall] = []
        for raw_call in message.get("tool_calls") or []:
            try:
                function = raw_call["function"]
                arguments_raw = function.get("arguments") or "{}"
                arguments = json.loads(arguments_raw)
                if not isinstance(arguments, dict):
                    raise TypeError("tool arguments must decode to an object")
                tool_calls.append(
                    ToolCall(
                        id=str(raw_call["id"]),
                        name=str(function["name"]),
                        arguments=arguments,
                    )
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ProviderProtocolError("invalid provider tool call") from exc

        metadata: dict[str, Any] = {
            "response_id": data.get("id"),
            "finish_reason": choice.get("finish_reason"),
        }
        if isinstance(data.get("usage"), dict):
            metadata["usage"] = data["usage"]
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=tuple(tool_calls),
            metadata=metadata,
        )

    def _endpoint(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"

    @staticmethod
    def _tool_payload(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }

    @staticmethod
    def _message_payload(message: AgentMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(
                            call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role == "tool":
            if message.tool_call_id is None:
                raise ValueError("tool message requires tool_call_id")
            payload["tool_call_id"] = message.tool_call_id
        return payload
