"""Standalone Responses adapter for a Codex-maintained ChatGPT login.

This experimental adapter deliberately is not registered by ``agent.factory``.
It reconstructs each request from the complete generic message history supplied
by the caller and does not use remote conversation state.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from ah_there_it_is.agent.codex_credentials import (
    ChatGPTCredentialSource,
    CodexAuthFileCredentialSource,
    CredentialSourceError,
)
from ah_there_it_is.agent.errors import ProviderProtocolError, ProviderRequestError
from ah_there_it_is.agent.metadata import redact_sensitive_text
from ah_there_it_is.agent.protocol import (
    AgentMessage,
    LLMClientInfo,
    LLMResponse,
    ToolCall,
    ToolDefinition,
)


CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_ORIGINATOR = "codex_cli_rs"
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 2.0


@dataclass(frozen=True)
class ChatGPTCodexConfig:
    model: str
    timeout_seconds: float = 60.0
    max_retries: int = 1
    retry_backoff_seconds: float = 0.25
    max_response_bytes: int = 2 * 1024 * 1024
    endpoint: str = CODEX_RESPONSES_URL


class ChatGPTCodexLLMClient:
    """Synchronous, bounded HTTP/SSE Responses client for Codex OAuth."""

    def __init__(
        self,
        config: ChatGPTCodexConfig,
        *,
        credential_source: ChatGPTCredentialSource | None = None,
        client: httpx.Client | None = None,
        sleep=time.sleep,
    ) -> None:
        if not config.model.strip():
            raise ValueError("model must not be empty")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if config.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if config.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")
        if config.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be > 0")
        self.config = config
        self._credential_source = credential_source or CodexAuthFileCredentialSource()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(config.timeout_seconds),
            limits=httpx.Limits(
                max_connections=4,
                max_keepalive_connections=4,
                keepalive_expiry=30.0,
            ),
            follow_redirects=False,
            trust_env=False,
        )
        self._sleep = sleep

    @property
    def info(self) -> LLMClientInfo:
        return LLMClientInfo(
            provider="chatgpt-codex",
            model=self.config.model,
            config={
                "backend": "chatgpt.com/backend-api/codex/responses",
                "transport": "http-sse",
                "store": False,
                "stream": True,
                "timeout_seconds": self.config.timeout_seconds,
                "max_response_bytes": self.config.max_response_bytes,
            },
        )

    def close(self) -> None:
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> "ChatGPTCodexLLMClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse:
        body = self._request_payload(messages, tools)
        started = time.perf_counter()
        attempts = 0
        for attempt in range(self.config.max_retries + 1):
            attempts = attempt + 1
            try:
                credentials = self._credential_source.get()
            except CredentialSourceError as exc:
                raise ProviderRequestError(str(exc)) from None
            except Exception:
                raise ProviderRequestError("ChatGPT credential source failed") from None

            try:
                with self._client.stream(
                    "POST",
                    self.config.endpoint,
                    json=body,
                    headers=self._headers(
                        credentials.access_token, credentials.account_id
                    ),
                    follow_redirects=False,
                ) as response:
                    if response.status_code >= 400:
                        detail = self._safe_upstream_error(
                            response, credentials.access_token, credentials.account_id
                        )
                        if (
                            response.status_code not in _TRANSIENT_STATUS_CODES
                            or attempt >= self.config.max_retries
                        ):
                            raise ProviderRequestError(
                                f"ChatGPT Codex backend HTTP {response.status_code}"
                                + (f": {detail}" if detail else "")
                            ) from None
                        delay = self._retry_delay(
                            attempt, response.headers.get("Retry-After")
                        )
                        self._sleep(delay)
                        continue

                    try:
                        parsed = parse_responses_sse(
                            response.iter_bytes(),
                            max_bytes=self.config.max_response_bytes,
                            secrets=(credentials.access_token, credentials.account_id or ""),
                        )
                    except ProviderRequestError:
                        raise
                    except httpx.TimeoutException:
                        raise ProviderRequestError(
                            "ChatGPT Codex response timed out"
                        ) from None
                    except httpx.RequestError:
                        raise ProviderRequestError(
                            "ChatGPT Codex response stream failed"
                        ) from None
                    transport = {
                        "client_wall_seconds": round(time.perf_counter() - started, 6),
                        "attempts": attempts,
                        "transport": "http-sse",
                    }
                    return LLMResponse(
                        content=parsed["content"],
                        tool_calls=tuple(parsed["tool_calls"]),
                        metadata={
                            "response_id": parsed.get("response_id"),
                            "transport": transport,
                        },
                    )
            except ProviderRequestError:
                raise
            except httpx.TimeoutException:
                if attempt >= self.config.max_retries:
                    raise ProviderRequestError(
                        "ChatGPT Codex request timed out"
                    ) from None
                self._sleep(self._retry_delay(attempt, None))
            except httpx.RequestError:
                if attempt >= self.config.max_retries:
                    raise ProviderRequestError(
                        "ChatGPT Codex request failed"
                    ) from None
                self._sleep(self._retry_delay(attempt, None))
            except Exception:
                raise ProviderRequestError("ChatGPT Codex request failed") from None

        raise ProviderRequestError("ChatGPT Codex request failed")

    def _headers(
        self, access_token: str, account_id: str | None
    ) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "originator": CODEX_ORIGINATOR,
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "codex_cli_rs/0.156.1",
        }
        if account_id:
            headers["ChatGPT-Account-ID"] = account_id
        return headers

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return min(max(0.0, float(retry_after)), _MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass
        return min(
            self.config.retry_backoff_seconds * (2**attempt),
            _MAX_RETRY_AFTER_SECONDS,
        )

    def _request_payload(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> dict[str, Any]:
        system_text = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "system":
                continue
            if message.role in ("user", "assistant") and message.content:
                content_type = "input_text" if message.role == "user" else "output_text"
                input_items.append(
                    {
                        "role": message.role,
                        "content": [{"type": content_type, "text": message.content}],
                    }
                )
            if message.role == "assistant":
                for call in message.tool_calls:
                    input_items.append(
                        {
                            "type": "function_call",
                            "call_id": call.id,
                            "name": call.name,
                            "arguments": json.dumps(
                                call.arguments, ensure_ascii=False, separators=(",", ":")
                            ),
                        }
                    )
            elif message.role == "tool":
                if not message.tool_call_id:
                    raise ProviderProtocolError("tool result is missing its call ID")
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )

        payload: dict[str, Any] = {
            "model": self.config.model,
            "instructions": system_text,
            "input": input_items,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "store": False,
            "stream": True,
            "include": [],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                    "strict": False,
                }
                for tool in tools
            ]
        return payload

    def _safe_upstream_error(
        self,
        response: httpx.Response,
        access_token: str,
        account_id: str | None,
    ) -> str:
        try:
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=4096):
                remaining = 16 * 1024 - len(data)
                if remaining <= 0:
                    break
                data.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    break
            parsed = json.loads(bytes(data))
        except Exception:
            return ""
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if not isinstance(error, dict):
            return ""
        code = error.get("code")
        message = error.get("message")
        parts = []
        if isinstance(code, str) and code:
            parts.append(code[:120])
        if isinstance(message, str) and message:
            parts.append(message[:1000])
        return redact_sensitive_text(
            ": ".join(parts),
            (access_token, account_id or ""),
        )


def parse_responses_sse(
    chunks: Iterable[bytes],
    *,
    max_bytes: int = 2 * 1024 * 1024,
    secrets: Iterable[str] = (),
) -> dict[str, Any]:
    """Parse bounded SSE and require a completed Responses event."""
    total_bytes = 0
    buffer = bytearray()
    data_lines: list[str] = []
    event_name = ""
    text_deltas: list[str] = []
    calls: dict[str, dict[str, str]] = {}
    completed: dict[str, Any] | None = None

    def dispatch() -> None:
        nonlocal event_name, data_lines, completed
        if not data_lines:
            event_name = ""
            return
        raw_data = "\n".join(data_lines)
        data_lines = []
        name = event_name
        event_name = ""
        try:
            event = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError):
            raise ProviderProtocolError("malformed ChatGPT Codex SSE event") from None
        if not isinstance(event, dict):
            raise ProviderProtocolError("invalid ChatGPT Codex SSE event")
        kind = event.get("type") or name
        if kind in {"error", "response.failed"}:
            upstream_error = event.get("error") or event.get("response") or {}
            if isinstance(upstream_error, dict):
                code = upstream_error.get("code")
                message = upstream_error.get("message")
                detail = ": ".join(
                    str(part)[:1000]
                    for part in (code, message)
                    if isinstance(part, str) and part
                )
            else:
                detail = ""
            safe_detail = redact_sensitive_text(detail, secrets)
            raise ProviderRequestError(
                "ChatGPT Codex stream returned an error"
                + (f": {safe_detail}" if safe_detail else "")
            ) from None
        if kind == "response.output_text.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                text_deltas.append(delta)
        elif kind == "response.output_item.added":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                item_id = item.get("id") or item.get("call_id")
                if isinstance(item_id, str):
                    calls[item_id] = {
                        "id": str(item.get("call_id") or ""),
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or ""),
                    }
        elif kind == "response.function_call_arguments.delta":
            item_id = event.get("item_id")
            delta = event.get("delta")
            if isinstance(item_id, str) and isinstance(delta, str):
                entry = calls.setdefault(item_id, {"id": "", "name": "", "arguments": ""})
                entry["arguments"] += delta
        elif kind == "response.function_call_arguments.done":
            item_id = event.get("item_id")
            arguments = event.get("arguments")
            if isinstance(item_id, str) and isinstance(arguments, str):
                entry = calls.setdefault(item_id, {"id": "", "name": "", "arguments": ""})
                entry["arguments"] = arguments
        elif kind == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "function_call":
                item_id = item.get("id") or item.get("call_id")
                if isinstance(item_id, str):
                    calls[item_id] = {
                        "id": str(item.get("call_id") or ""),
                        "name": str(item.get("name") or ""),
                        "arguments": str(item.get("arguments") or ""),
                    }
        elif kind == "response.completed":
            response_data = event.get("response")
            if not isinstance(response_data, dict):
                raise ProviderProtocolError("completed response is missing its payload")
            if response_data.get("status") not in (None, "completed"):
                raise ProviderProtocolError("ChatGPT Codex response did not complete")
            completed = response_data

    def process_line(line: bytes) -> None:
        nonlocal event_name
        if line.endswith(b"\r"):
            line = line[:-1]
        if not line:
            dispatch()
        elif line.startswith(b":"):
            return
        else:
            field, separator, value = line.partition(b":")
            if separator and value.startswith(b" "):
                value = value[1:]
            try:
                decoded = value.decode("utf-8")
            except UnicodeDecodeError:
                raise ProviderProtocolError("invalid UTF-8 in ChatGPT Codex SSE") from None
            if field == b"data":
                data_lines.append(decoded)
            elif field == b"event":
                event_name = decoded

    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise ProviderProtocolError("invalid ChatGPT Codex SSE chunk")
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise ProviderProtocolError("ChatGPT Codex response exceeded size limit")
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(buffer[:newline])
            del buffer[: newline + 1]
            process_line(line)
        if len(buffer) > max_bytes:
            raise ProviderProtocolError("ChatGPT Codex SSE event exceeded size limit")
    if buffer:
        process_line(bytes(buffer))
    if data_lines:
        dispatch()
    if completed is None:
        raise ProviderProtocolError("ChatGPT Codex stream ended before completion")

    response_id = completed.get("id") if isinstance(completed.get("id"), str) else None
    output = completed.get("output")
    final_text: list[str] = []
    final_calls: list[ToolCall] = []
    if output is not None:
        if not isinstance(output, list):
            raise ProviderProtocolError("invalid ChatGPT Codex output list")
        for item in output:
            if not isinstance(item, dict):
                raise ProviderProtocolError("invalid ChatGPT Codex output item")
            if item.get("type") == "message":
                content = item.get("content")
                if not isinstance(content, list):
                    raise ProviderProtocolError("invalid ChatGPT Codex message content")
                for part in content:
                    if isinstance(part, dict) and part.get("type") in (
                        "output_text", "text",
                    ) and isinstance(part.get("text"), str):
                        final_text.append(part["text"])
            elif item.get("type") == "function_call":
                final_calls.append(_decode_function_call(item))
    if not final_text:
        final_text = text_deltas
    if output is None:
        for call in calls.values():
            final_calls.append(_decode_function_call(call))
    try:
        return {
            "content": "".join(final_text),
            "tool_calls": final_calls,
            "response_id": response_id,
        }
    except ValidationError:
        raise ProviderProtocolError("invalid ChatGPT Codex response") from None


def _decode_function_call(item: dict[str, Any]) -> ToolCall:
    call_id = item.get("call_id") or item.get("id")
    name = item.get("name")
    raw_arguments = item.get("arguments")
    if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
        raise ProviderProtocolError("incomplete ChatGPT Codex function call")
    if not isinstance(raw_arguments, str):
        raise ProviderProtocolError("incomplete ChatGPT Codex function arguments")
    try:
        arguments = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError):
        raise ProviderProtocolError("invalid ChatGPT Codex function arguments") from None
    if not isinstance(arguments, dict):
        raise ProviderProtocolError("invalid ChatGPT Codex function arguments")
    try:
        return ToolCall(id=call_id, name=name, arguments=arguments)
    except ValidationError:
        raise ProviderProtocolError("invalid ChatGPT Codex function call") from None
