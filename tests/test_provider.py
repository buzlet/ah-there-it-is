from __future__ import annotations

import json
import threading

import httpx
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ah_there_it_is.agent.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
    ProviderProtocolError,
)
from ah_there_it_is.agent.protocol import AgentMessage, ToolCall, ToolDefinition


class _Handler(BaseHTTPRequestHandler):
    response_payload: dict = {}
    request_payload: dict | None = None
    authorization: str | None = None
    headers_seen: dict[str, str] = {}

    def do_POST(self):  # noqa: N802 - stdlib callback name
        length = int(self.headers["Content-Length"])
        type(self).request_payload = json.loads(self.rfile.read(length))
        type(self).authorization = self.headers.get("Authorization")
        type(self).headers_seen = dict(self.headers.items())
        payload = json.dumps(type(self).response_payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):  # noqa: A002
        return


def _server(payload: dict):
    _Handler.response_payload = payload
    _Handler.request_payload = None
    _Handler.authorization = None
    _Handler.headers_seen = {}
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_openai_compatible_adapter_serializes_tools_and_parses_call() -> None:
    server, thread = _server(
        {
            "id": "resp-1",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "search_items",
                                    "arguments": '{"query":"CH341A"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }
    )
    try:
        client = OpenAICompatibleLLMClient(
            OpenAICompatibleConfig(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model="test-model",
                api_key="secret",
                provider_name="fake-provider",
                temperature=0.2,
            )
        )
        response = client.complete(
            [AgentMessage(role="user", content="Где CH341A?")],
            [
                ToolDefinition(
                    name="search_items",
                    description="Search items",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                )
            ],
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert response.tool_calls[0].name == "search_items"
    assert response.tool_calls[0].arguments == {"query": "CH341A"}
    assert response.metadata["finish_reason"] == "tool_calls"
    assert response.metadata["usage"]["total_tokens"] == 14
    assert _Handler.authorization == "Bearer secret"
    assert _Handler.request_payload["model"] == "test-model"
    assert _Handler.request_payload["temperature"] == 0.2
    assert _Handler.request_payload["tools"][0]["function"]["name"] == "search_items"


def test_openai_compatible_adapter_does_not_log_api_key() -> None:
    client = OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            base_url="http://localhost:1234/v1",
            model="local-model",
            api_key="top-secret",
        )
    )
    assert "api_key" not in client.info.config
    assert "top-secret" not in json.dumps(client.info.model_dump())


def test_openai_compatible_adapter_rejects_invalid_tool_json() -> None:
    server, thread = _server(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "bad",
                                "function": {"name": "search_items", "arguments": "not-json"},
                            }
                        ],
                    },
                }
            ]
        }
    )
    try:
        client = OpenAICompatibleLLMClient(
            OpenAICompatibleConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                model="test-model",
            )
        )
        with pytest.raises(ProviderProtocolError):
            client.complete([AgentMessage(role="user", content="x")], [])
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_gemini_adapter_serializes_tools_and_preserves_thought_signature() -> None:
    from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient

    server, thread = _server(
        {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "id": "fc-1",
                                    "name": "search_items",
                                    "args": {"query": "CH341A"},
                                },
                                "thoughtSignature": "opaque-signature",
                            }
                        ],
                    },
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "totalTokenCount": 20},
            "modelVersion": "gemini-test",
            "responseId": "resp-gemini-1",
        }
    )
    try:
        client = GeminiLLMClient(
            GeminiConfig(
                base_url=f"http://127.0.0.1:{server.server_port}",
                model="gemini-test",
                api_key="secret",
                temperature=0.1,
            )
        )
        tools = [
            ToolDefinition(
                name="search_items",
                description="Search items",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
        ]
        first = client.complete(
            [
                AgentMessage(role="system", content="Use tools."),
                AgentMessage(role="user", content="Где CH341A?"),
            ],
            tools,
        )
        first_request = _Handler.request_payload
        assert first.tool_calls[0].provider_state["thought_signature"] == "opaque-signature"
        assert first.model_dump()["tool_calls"][0].get("provider_state") is None
        assert first_request["systemInstruction"]["parts"][0]["text"] == "Use tools."
        assert first_request["tools"][0]["functionDeclarations"][0]["name"] == "search_items"
        assert first_request["generationConfig"]["temperature"] == 0.1

        _Handler.response_payload = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [{"text": "Нашёл."}]},
                }
            ],
            "modelVersion": "gemini-test",
            "responseId": "resp-gemini-2",
        }
        response = client.complete(
            [
                AgentMessage(role="system", content="Use tools."),
                AgentMessage(role="user", content="Где CH341A?"),
                AgentMessage(role="assistant", tool_calls=first.tool_calls),
                AgentMessage(
                    role="tool",
                    content='{"ok":true,"result":[{"id":7,"name":"CH341A"}]}',
                    tool_call_id="fc-1",
                    tool_name="search_items",
                ),
            ],
            tools,
        )
        second_request = _Handler.request_payload
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    model_part = second_request["contents"][1]["parts"][0]
    assert model_part["functionCall"]["id"] == "fc-1"
    assert model_part["thoughtSignature"] == "opaque-signature"
    function_response = second_request["contents"][2]["parts"][0]["functionResponse"]
    assert function_response["id"] == "fc-1"
    assert function_response["name"] == "search_items"
    assert function_response["response"]["ok"] is True
    assert response.content == "Нашёл."


def test_gemini_adapter_groups_parallel_tool_responses() -> None:
    from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient

    client = GeminiLLMClient(GeminiConfig(base_url="http://localhost", model="x"))
    contents = client._contents(  # noqa: SLF001 - serialization invariant under test
        [
            AgentMessage(role="user", content="find both"),
            AgentMessage(
                role="assistant",
                tool_calls=(
                    ToolCall(id="a", name="search_items", arguments={"query": "a"}),
                    ToolCall(id="b", name="search_items", arguments={"query": "b"}),
                ),
            ),
            AgentMessage(role="tool", content='{"ok":true}', tool_call_id="a", tool_name="search_items"),
            AgentMessage(role="tool", content='{"ok":true}', tool_call_id="b", tool_name="search_items"),
        ]
    )
    assert len(contents) == 3
    assert len(contents[2]["parts"]) == 2
    assert [part["functionResponse"]["id"] for part in contents[2]["parts"]] == ["a", "b"]


def test_gemini_schema_resolves_pydantic_defs_and_nullable() -> None:
    from ah_there_it_is.agent.gemini import _gemini_json_schema
    from ah_there_it_is.agent.schemas import CreateItemInput

    schema = _gemini_json_schema(CreateItemInput.model_json_schema())
    assert "$defs" not in schema
    assert "$ref" not in json.dumps(schema)
    assert schema["properties"]["state"]["enum"]
    assert schema["properties"]["location_id"]["type"] == ["integer", "null"]
    assert schema["properties"]["location_id"]["minimum"] == 1


def test_gemini_adapter_does_not_log_api_key() -> None:
    from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient

    client = GeminiLLMClient(GeminiConfig(model="gemini-test", api_key="top-secret"))
    assert "api_key" not in client.info.config
    assert "top-secret" not in json.dumps(client.info.model_dump())


def test_factory_builds_native_gemini_client() -> None:
    from ah_there_it_is.agent.factory import build_llm_factory
    from ah_there_it_is.agent.gemini import GeminiLLMClient
    from ah_there_it_is.config import Settings

    client = build_llm_factory(
        Settings(
            llm_provider="gemini",
            llm_provider_name="google-gemini",
            llm_model="gemini-flash-latest",
            llm_api_key="secret",
        )
    )()
    assert isinstance(client, GeminiLLMClient)
    assert client.info.provider == "google-gemini"
    assert client.info.model == "gemini-flash-latest"
    assert "secret" not in json.dumps(client.info.model_dump())


def test_gemini_adapter_retries_transient_http_errors(monkeypatch) -> None:
    import io
    from urllib.error import HTTPError

    import ah_there_it_is.agent.gemini as gemini_module
    from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient

    calls = 0
    sleeps: list[float] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"role": "model", "parts": [{"text": "OK"}]},
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise HTTPError(
                request.full_url,
                503,
                "high demand",
                hdrs={},
                fp=io.BytesIO(b'{"error":"high demand"}'),
            )
        return _Response()

    monkeypatch.setattr(gemini_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(gemini_module.time, "sleep", sleeps.append)

    client = GeminiLLMClient(
        GeminiConfig(
            model="gemini-test",
            max_retries=2,
            retry_backoff_seconds=0.5,
        )
    )
    response = client.complete([AgentMessage(role="user", content="OK?")], [])

    assert response.content == "OK"
    assert calls == 3
    assert sleeps == [0.5, 1.0]
    assert client.info.config["max_retries"] == 2
    assert client.info.config["retry_backoff_seconds"] == 0.5

def test_gemini_adapter_does_not_retry_http_429(monkeypatch) -> None:
    import io
    from urllib.error import HTTPError

    import ah_there_it_is.agent.gemini as gemini_module
    from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient

    calls = 0

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(
            request.full_url,
            429,
            "quota",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED"}}'),
        )

    monkeypatch.setattr(gemini_module, "urlopen", fake_urlopen)
    client = GeminiLLMClient(GeminiConfig(model="gemini-test", max_retries=5))

    with pytest.raises(Exception, match="provider HTTP 429"):
        client.complete([AgentMessage(role="user", content="x")], [])

    assert calls == 1


def test_gemini_adapter_retries_timeout(monkeypatch) -> None:
    import ah_there_it_is.agent.gemini as gemini_module
    from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient

    calls = 0

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {"role": "model", "parts": [{"text": "OK"}]},
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("read timed out")
        return _Response()

    monkeypatch.setattr(gemini_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(gemini_module.time, "sleep", lambda delay: None)
    client = GeminiLLMClient(
        GeminiConfig(model="gemini-test", max_retries=1, retry_backoff_seconds=0)
    )

    assert client.complete([AgentMessage(role="user", content="x")], []).content == "OK"
    assert calls == 2


def test_openai_compatible_adapter_retries_transient_http_429(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0"},
                json={"error": "rate limit"},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "id": "ok",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
            },
            request=request,
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    import ah_there_it_is.agent.openai_compatible as provider_module

    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)
    client = OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            base_url="https://api.example/v1",
            model="test-model",
            max_retries=1,
            retry_backoff_seconds=0,
        ),
        client=http_client,
    )
    try:
        response = client.complete([AgentMessage(role="user", content="x")], [])
    finally:
        http_client.close()

    assert response.content == "OK"
    assert response.metadata["transport"]["attempts"] == 2
    assert response.metadata["transport"]["retry_events"] == [
        {
            "kind": "http",
            "status": 429,
            "delay_seconds": 0.0,
            "retry_after_seconds": 0.0,
        }
    ]
    assert response.metadata["transport"]["client_wall_seconds"] >= 0
    assert calls == 2
    assert sleeps == []


def test_openai_compatible_adapter_caps_retry_after(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "999"},
                json={"error": "rate limit"},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "id": "ok-after-cap",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
            },
            request=request,
        )

    import ah_there_it_is.agent.openai_compatible as provider_module

    monkeypatch.setattr(provider_module.time, "sleep", sleeps.append)
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            base_url="https://api.example/v1",
            model="test-model",
            max_retries=1,
            retry_backoff_seconds=1,
            max_retry_delay_seconds=3,
        ),
        client=http_client,
    )
    try:
        response = client.complete([AgentMessage(role="user", content="x")], [])
    finally:
        http_client.close()

    assert response.content == "OK"
    assert calls == 2
    assert sleeps == [3]
    assert response.metadata["transport"]["retry_events"] == [
        {
            "kind": "http",
            "status": 429,
            "delay_seconds": 3,
            "retry_after_seconds": 999.0,
        }
    ]
    assert client.info.config["max_retry_delay_seconds"] == 3


def test_openai_compatible_adapter_sends_groq_style_extra_body() -> None:
    server, thread = _server(
        {
            "id": "resp-groq",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "OK"},
                }
            ],
        }
    )
    try:
        client = OpenAICompatibleLLMClient(
            OpenAICompatibleConfig(
                base_url=f"http://127.0.0.1:{server.server_port}/openai/v1",
                model="qwen/qwen3.8-27b",
                temperature=0.6,
                extra_body={
                    "max_completion_tokens": 2048,
                    "top_p": 0.95,
                    "reasoning_effort": "default",
                    "reasoning_format": "hidden",
                },
            )
        )
        client.complete([AgentMessage(role="user", content="x")], [])
        request = _Handler.request_payload
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert request["model"] == "qwen/qwen3.8-27b"
    assert request["temperature"] == 0.6
    assert request["max_completion_tokens"] == 2048
    assert request["top_p"] == 0.95
    assert request["reasoning_effort"] == "default"
    assert request["reasoning_format"] == "hidden"

def test_openai_compatible_adapter_sends_api_client_headers() -> None:
    server, thread = _server(
        {
            "id": "resp-headers",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "OK"},
                }
            ],
        }
    )
    try:
        client = OpenAICompatibleLLMClient(
            OpenAICompatibleConfig(
                base_url=f"http://127.0.0.1:{server.server_port}/v1",
                model="test-model",
            )
        )
        client.complete([AgentMessage(role="user", content="x")], [])
        user_agent = _Handler.headers_seen.get("User-Agent")
        accept = _Handler.headers_seen.get("Accept")
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert user_agent.startswith("ah-there-it-is/")
    assert accept == "application/json"


def test_openai_compatible_adapter_preserves_backend_fingerprint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "fingerprinted",
                "model": "qwen/qwen3.8-27b",
                "system_fingerprint": "fp_test_backend",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
            },
            request=request,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            base_url="https://api.example/v1",
            model="qwen/qwen3.8-27b",
        ),
        client=http_client,
    )
    try:
        response = client.complete([AgentMessage(role="user", content="x")], [])
    finally:
        http_client.close()

    assert response.metadata["response_model"] == "qwen/qwen3.8-27b"
    assert response.metadata["system_fingerprint"] == "fp_test_backend"


def test_openai_compatible_adapter_reports_provider_and_client_timing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "timed",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "OK"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                    "total_time": 0.01,
                },
            },
            request=request,
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleLLMClient(
        OpenAICompatibleConfig(
            base_url="https://api.example/v1",
            model="test-model",
        ),
        client=http_client,
    )
    try:
        first = client.complete([AgentMessage(role="user", content="one")], [])
        second = client.complete([AgentMessage(role="user", content="two")], [])
    finally:
        http_client.close()

    assert first.metadata["provider_server_seconds"] == 0.01
    assert first.metadata["transport"]["attempts"] == 1
    assert first.metadata["transport"]["client_wall_seconds"] >= 0
    assert first.metadata["client_minus_provider_seconds"] >= 0
    assert second.metadata["transport"]["attempts"] == 1
    assert client.info.config["transport"] == "httpx-persistent"
