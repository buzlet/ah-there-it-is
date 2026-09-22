"""Synchronous OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

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
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    max_retry_delay_seconds: float = 60.0


class OpenAICompatibleLLMClient:
    """Call a provider implementing the OpenAI chat-completions tool format.

    One persistent httpx.Client is reused for the life of this adapter so
    multi-round tool loops retain HTTP keep-alive connections.
    """

    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not config.base_url.strip():
            raise ValueError("base_url must not be empty")
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if config.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if config.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")
        if config.max_retry_delay_seconds < 0:
            raise ValueError("max_retry_delay_seconds must be >= 0")
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(config.timeout_seconds),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=10,
                keepalive_expiry=60.0,
            ),
            follow_redirects=True,
        )

    @property
    def info(self) -> LLMClientInfo:
        logged_config: dict[str, Any] = {
            "base_url": self.config.base_url.rstrip("/"),
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
            "retry_backoff_seconds": self.config.retry_backoff_seconds,
            "max_retry_delay_seconds": self.config.max_retry_delay_seconds,
            "transport": "httpx-persistent",
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

    def close(self) -> None:
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> "OpenAICompatibleLLMClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

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

        raw, transport = self._post_with_retry(body)

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
            "response_model": data.get("model"),
            "system_fingerprint": data.get("system_fingerprint"),
            "finish_reason": choice.get("finish_reason"),
            "transport": transport,
        }
        usage = data.get("usage")
        if isinstance(usage, dict):
            metadata["usage"] = usage
            provider_seconds = usage.get("total_time")
            if isinstance(provider_seconds, (int, float)):
                metadata["provider_server_seconds"] = float(provider_seconds)
                metadata["client_minus_provider_seconds"] = round(
                    max(0.0, transport["client_wall_seconds"] - float(provider_seconds)),
                    6,
                )
        return LLMResponse(
            content=message.get("content") or "",
            tool_calls=tuple(tool_calls),
            metadata=metadata,
        )

    def _post_with_retry(self, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        transient_statuses = {429, 500, 502, 503, 504}
        started = time.perf_counter()
        attempts = 0
        retry_events: list[dict[str, Any]] = []

        for attempt in range(self.config.max_retries + 1):
            attempts = attempt + 1
            try:
                response = self._client.post(
                    self._endpoint(),
                    json=body,
                    headers=self._headers(),
                )
            except httpx.TimeoutException as exc:
                if attempt >= self.config.max_retries:
                    raise ProviderRequestError("provider request timed out") from exc
                delay, _ = self._retry_sleep(attempt)
                retry_events.append(
                    {"kind": "timeout", "delay_seconds": round(delay, 6)}
                )
                continue
            except httpx.RequestError as exc:
                if attempt >= self.config.max_retries:
                    raise ProviderRequestError(
                        f"provider request failed: {exc}"
                    ) from exc
                delay, _ = self._retry_sleep(attempt)
                retry_events.append(
                    {
                        "kind": "request_error",
                        "delay_seconds": round(delay, 6),
                    }
                )
                continue

            if response.status_code >= 400:
                detail = response.text[:4000]
                if (
                    response.status_code not in transient_statuses
                    or attempt >= self.config.max_retries
                ):
                    raise ProviderRequestError(
                        f"provider HTTP {response.status_code}: "
                        f"{detail or response.reason_phrase}"
                    )
                retry_after_header = response.headers.get("Retry-After")
                retry_after = self._parse_retry_after(retry_after_header)
                if (
                    retry_after is not None
                    and retry_after > self.config.max_retry_delay_seconds
                ):
                    raise ProviderRequestError(
                        f"provider HTTP {response.status_code}: "
                        f"Retry-After {retry_after:g}s exceeds configured "
                        f"retry-delay cap {self.config.max_retry_delay_seconds:g}s; "
                        f"{detail or response.reason_phrase}"
                    )
                delay, retry_after = self._retry_sleep(
                    attempt, retry_after_header
                )
                event: dict[str, Any] = {
                    "kind": "http",
                    "status": response.status_code,
                    "delay_seconds": round(delay, 6),
                }
                if retry_after is not None:
                    event["retry_after_seconds"] = round(retry_after, 6)
                retry_events.append(event)
                continue

            wall = time.perf_counter() - started
            return response.text, {
                "client_wall_seconds": round(wall, 6),
                "attempts": attempts,
                "http_version": response.http_version,
                "retry_events": retry_events,
            }

        raise AssertionError("retry loop exhausted unexpectedly")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ah-there-it-is/0.2 (+https://github.com/buzlet/ah-there-it-is)",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    @staticmethod
    def _parse_retry_after(retry_after: str | None) -> float | None:
        if not retry_after:
            return None
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    def _retry_sleep(
        self,
        attempt: int,
        retry_after: str | None = None,
    ) -> tuple[float, float | None]:
        delay = self.config.retry_backoff_seconds * (2**attempt)
        retry_after_seconds = self._parse_retry_after(retry_after)
        if retry_after_seconds is not None:
            delay = max(delay, retry_after_seconds)
        delay = min(delay, self.config.max_retry_delay_seconds)
        if delay > 0:
            time.sleep(delay)
        return delay, retry_after_seconds

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
