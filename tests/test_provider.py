from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ah_there_it_is.agent.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleLLMClient,
    ProviderProtocolError,
)
from ah_there_it_is.agent.protocol import AgentMessage, ToolDefinition


class _Handler(BaseHTTPRequestHandler):
    response_payload: dict = {}
    request_payload: dict | None = None
    authorization: str | None = None

    def do_POST(self):  # noqa: N802 - stdlib callback name
        length = int(self.headers["Content-Length"])
        type(self).request_payload = json.loads(self.rfile.read(length))
        type(self).authorization = self.headers.get("Authorization")
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
