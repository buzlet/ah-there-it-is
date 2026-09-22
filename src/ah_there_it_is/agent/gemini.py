"""Native Gemini generateContent adapter with function-calling state preservation."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ah_there_it_is.agent.errors import (
    ProviderProtocolError,
    ProviderRateLimitError,
    ProviderRequestError,
)
from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClientInfo,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)


DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class GeminiConfig:
    model: str
    api_key: str | None = None
    base_url: str = DEFAULT_GEMINI_BASE_URL
    provider_name: str = "gemini"
    timeout_seconds: float = 60.0
    temperature: float | None = None
    extra_body: dict[str, Any] | None = None
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0


class GeminiLLMClient:
    """Minimal synchronous client for Gemini's native generateContent REST API."""

    def __init__(self, config: GeminiConfig) -> None:
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if not config.base_url.strip():
            raise ValueError("base_url must not be empty")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if config.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if config.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")
        self.config = config
        self._synthetic_call_ids: set[str] = set()

    @property
    def info(self) -> LLMClientInfo:
        logged_config: dict[str, Any] = {
            "base_url": self.config.base_url.rstrip("/"),
            "timeout_seconds": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
            "retry_backoff_seconds": self.config.retry_backoff_seconds,
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
        body = self._request_body(messages, tools)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["X-goog-api-key"] = self.config.api_key
        raw = self._post_with_retry(payload, headers)

        try:
            data = json.loads(raw)
            candidate = data["candidates"][0]
            content = candidate["content"]
            parts = content.get("parts") or []
            if not isinstance(parts, list):
                raise TypeError("candidate parts must be a list")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderProtocolError("invalid Gemini generateContent response") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        response_id = str(data.get("responseId") or "response")
        for index, part in enumerate(parts):
            if not isinstance(part, dict):
                raise ProviderProtocolError("invalid Gemini content part")
            if "text" in part and not part.get("thought"):
                text_parts.append(str(part.get("text") or ""))
            function_call = part.get("functionCall")
            if function_call is None:
                continue
            if not isinstance(function_call, dict):
                raise ProviderProtocolError("invalid Gemini functionCall")
            try:
                name = str(function_call["name"])
                arguments = function_call.get("args") or {}
                if not isinstance(arguments, dict):
                    raise TypeError("function args must be an object")
            except (KeyError, TypeError) as exc:
                raise ProviderProtocolError("invalid Gemini functionCall") from exc

            provider_id = function_call.get("id")
            if provider_id is None:
                call_id = f"gemini-{response_id}-{index}"
                self._synthetic_call_ids.add(call_id)
            else:
                call_id = str(provider_id)
            provider_state: dict[str, Any] = {}
            if "thoughtSignature" in part:
                provider_state["thought_signature"] = part["thoughtSignature"]
            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=arguments,
                    provider_state=provider_state,
                )
            )

        metadata: dict[str, Any] = {
            "response_id": data.get("responseId"),
            "model_version": data.get("modelVersion"),
            "finish_reason": candidate.get("finishReason"),
        }
        if isinstance(data.get("usageMetadata"), dict):
            metadata["usage"] = data["usageMetadata"]
        return LLMResponse(
            content="".join(text_parts),
            tool_calls=tuple(tool_calls),
            metadata=metadata,
        )

    def _post_with_retry(self, payload: bytes, headers: dict[str, str]) -> str:
        transient_statuses = {500, 502, 503, 504}
        for attempt in range(self.config.max_retries + 1):
            request = Request(self._endpoint(), data=payload, headers=headers, method="POST")
            try:
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    return response.read().decode("utf-8")
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:4000]
                if exc.code == 429:
                    retry_after: float | None = None
                    if exc.headers:
                        raw_retry_after = exc.headers.get("Retry-After")
                        if raw_retry_after:
                            try:
                                retry_after = max(0.0, float(raw_retry_after))
                            except ValueError:
                                pass
                    raise ProviderRateLimitError(
                        f"provider HTTP 429: {detail or exc.reason}",
                        retry_after_seconds=retry_after,
                    ) from exc
                if exc.code not in transient_statuses or attempt >= self.config.max_retries:
                    raise ProviderRequestError(
                        f"provider HTTP {exc.code}: {detail or exc.reason}"
                    ) from exc
                self._retry_sleep(
                    attempt,
                    exc.headers.get("Retry-After") if exc.headers else None,
                )
            except TimeoutError as exc:
                if attempt >= self.config.max_retries:
                    raise ProviderRequestError("provider request timed out") from exc
                self._retry_sleep(attempt)
            except URLError as exc:
                if attempt >= self.config.max_retries:
                    raise ProviderRequestError(
                        f"provider request failed: {exc.reason}"
                    ) from exc
                self._retry_sleep(attempt)

        raise AssertionError("retry loop exhausted unexpectedly")

    def _retry_sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self.config.retry_backoff_seconds * (2**attempt)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        if delay > 0:
            time.sleep(delay)

    def _request_body(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> dict[str, Any]:
        system_text = "\n\n".join(
            message.content for message in messages if message.role == "system" and message.content
        )
        body: dict[str, Any] = {"contents": self._contents(messages)}
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "parametersJsonSchema": _gemini_json_schema(tool.input_schema),
                        }
                        for tool in tools
                    ]
                }
            ]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        if self.config.temperature is not None:
            body["generationConfig"] = {"temperature": self.config.temperature}
        if self.config.extra_body:
            protected = {
                "contents",
                "systemInstruction",
                "tools",
                "toolConfig",
                "generationConfig",
            }
            collision = protected.intersection(self.config.extra_body)
            if collision:
                raise ValueError(
                    "extra_body cannot override protected keys: "
                    + ", ".join(sorted(collision))
                )
            body.update(self.config.extra_body)
        return body

    def _contents(self, messages: Sequence[AgentMessage]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            if message.role == "system":
                index += 1
                continue
            if message.role == "tool":
                parts: list[dict[str, Any]] = []
                while index < len(messages) and messages[index].role == "tool":
                    parts.append(self._tool_response_part(messages[index]))
                    index += 1
                contents.append({"role": "user", "parts": parts})
                continue
            if message.role == "user":
                contents.append({"role": "user", "parts": [{"text": message.content}]})
                index += 1
                continue
            if message.role == "assistant":
                parts = []
                if message.content:
                    parts.append({"text": message.content})
                for call in message.tool_calls:
                    function_call: dict[str, Any] = {
                        "name": call.name,
                        "args": call.arguments,
                    }
                    if call.id not in self._synthetic_call_ids:
                        function_call["id"] = call.id
                    part: dict[str, Any] = {"functionCall": function_call}
                    signature = call.provider_state.get("thought_signature")
                    if signature is not None:
                        part["thoughtSignature"] = signature
                    parts.append(part)
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})
                index += 1
                continue
            raise ValueError(f"unsupported message role {message.role!r}")
        return contents

    def _tool_response_part(self, message: AgentMessage) -> dict[str, Any]:
        if message.tool_call_id is None or message.tool_name is None:
            raise ValueError("Gemini tool message requires tool_call_id and tool_name")
        try:
            result = json.loads(message.content) if message.content else {}
        except json.JSONDecodeError:
            result = {"result": message.content}
        if not isinstance(result, dict):
            result = {"result": result}
        function_response: dict[str, Any] = {
            "name": message.tool_name,
            "response": result,
        }
        if message.tool_call_id not in self._synthetic_call_ids:
            function_response["id"] = message.tool_call_id
        return {"functionResponse": function_response}

    def _endpoint(self) -> str:
        model = self.config.model.strip()
        if model.startswith("models/"):
            model = model[len("models/") :]
        return f"{self.config.base_url.rstrip('/')}/models/{quote(model, safe='')}:generateContent"


def _gemini_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local Pydantic refs and keep a Gemini-friendly JSON Schema subset."""

    defs = schema.get("$defs", {})

    def normalize(node: Any) -> Any:
        if isinstance(node, list):
            return [normalize(value) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            prefix = "#/$defs/"
            if not isinstance(ref, str) or not ref.startswith(prefix):
                raise ValueError(f"unsupported JSON Schema ref: {ref!r}")
            target = defs.get(ref[len(prefix) :])
            if not isinstance(target, dict):
                raise ValueError(f"unresolved JSON Schema ref: {ref!r}")
            merged = {**target, **{key: value for key, value in node.items() if key != "$ref"}}
            return normalize(merged)

        any_of = node.get("anyOf")
        if isinstance(any_of, list):
            normalized_options = [normalize(value) for value in any_of]
            nulls = [value for value in normalized_options if value.get("type") == "null"]
            non_null = [value for value in normalized_options if value.get("type") != "null"]
            if len(nulls) == 1 and len(non_null) == 1:
                result = dict(non_null[0])
                value_type = result.get("type")
                if isinstance(value_type, str):
                    result["type"] = [value_type, "null"]
                return _merge_schema_metadata(result, node)

        allowed = {
            "type",
            "properties",
            "required",
            "items",
            "additionalProperties",
            "enum",
            "description",
            "minimum",
            "maximum",
            "minItems",
            "maxItems",
        }
        result: dict[str, Any] = {}
        for key, value in node.items():
            if key in {"$defs", "anyOf", "title", "default"}:
                continue
            if key == "exclusiveMinimum" and isinstance(value, int):
                result["minimum"] = value + 1
                continue
            if key not in allowed:
                continue
            if key == "properties" and isinstance(value, dict):
                result[key] = {name: normalize(item) for name, item in value.items()}
            else:
                result[key] = normalize(value)
        return result

    normalized = normalize(schema)
    if not isinstance(normalized, dict):
        raise ValueError("tool schema must normalize to an object")
    return normalized


def _merge_schema_metadata(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key in ("description", "minimum", "maximum", "minItems", "maxItems"):
        if key in source and key not in target:
            target[key] = source[key]
    if "exclusiveMinimum" in source and "minimum" not in target:
        value = source["exclusiveMinimum"]
        if isinstance(value, int):
            target["minimum"] = value + 1
    return target
