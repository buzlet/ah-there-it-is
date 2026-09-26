"""Deterministic tests for the isolated ChatGPT/Codex Responses adapter."""

from __future__ import annotations

import json
from pathlib import Path
import time

import httpx
import pytest

from ah_there_it_is.agent.chatgpt_codex import (
    ChatGPTCodexConfig,
    ChatGPTCodexLLMClient,
    parse_responses_sse,
)
from ah_there_it_is.agent.codex_credentials import (
    ChatGPTCredentials,
    CodexAuthFileCredentialSource,
    CredentialSourceError,
    StaticChatGPTCredentialSource,
)
from ah_there_it_is.agent.errors import ProviderProtocolError, ProviderRequestError
from ah_there_it_is.agent.protocol import AgentMessage, ToolCall, ToolDefinition


TOKEN = "test-access-secret-value"
ACCOUNT = "test-account-secret-value"


def _sse_event(kind: str, data: dict) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode()


def _completed_response(output: list[dict], *, response_id: str = "resp_1") -> bytes:
    return _sse_event(
        "response.completed",
        {"type": "response.completed", "response": {
            "id": response_id, "status": "completed", "output": output,
        }},
    )


class Chunks(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes):
        self.chunks = chunks

    def __iter__(self):
        yield from self.chunks

    def close(self) -> None:
        return None


def _client(handler, *, source=None, retries: int = 0):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ChatGPTCodexLLMClient(
        ChatGPTCodexConfig(model="gpt-test", max_retries=retries),
        credential_source=source or StaticChatGPTCredentialSource(
            ChatGPTCredentials(TOKEN, ACCOUNT)
        ),
        client=http,
        sleep=lambda _seconds: None,
    )


def test_credential_source_reads_only_chatgpt_access_and_never_changes_file(
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": TOKEN,
            "refresh_token": "refresh-secret",
            "id_token": "id-secret",
            "account_id": ACCOUNT,
        },
    }))
    before = auth_file.read_bytes()
    source = CodexAuthFileCredentialSource(auth_file)

    credentials = source.get()
    assert credentials.access_token == TOKEN
    assert credentials.account_id == ACCOUNT
    assert "refresh-secret" not in repr(credentials)
    assert "id-secret" not in repr(credentials)
    assert auth_file.read_bytes() == before

    auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": "updated-token", "account_id": ACCOUNT},
    }))
    rewritten = auth_file.read_bytes()
    assert source.get().access_token == "updated-token"
    assert auth_file.read_bytes() == rewritten


@pytest.mark.parametrize("payload", [
    b"{invalid secret token=" + TOKEN.encode() + b"}",
    json.dumps({"auth_mode": "api", "tokens": {"access_token": TOKEN}}).encode(),
    json.dumps({"auth_mode": "chatgpt", "tokens": {"refresh_token": TOKEN}}).encode(),
])
def test_credential_source_rejects_bad_or_wrong_auth_without_mutation(
    tmp_path: Path,
    payload: bytes,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_bytes(payload)
    before = auth_file.read_bytes()

    with pytest.raises(CredentialSourceError) as raised:
        CodexAuthFileCredentialSource(auth_file).get()

    assert TOKEN not in str(raised.value)
    assert auth_file.read_bytes() == before


def test_credential_source_missing_file_fails_without_secret_detail(tmp_path: Path) -> None:
    with pytest.raises(CredentialSourceError, match="unavailable") as raised:
        CodexAuthFileCredentialSource(tmp_path / "missing-auth.json").get()
    assert TOKEN not in str(raised.value)


def test_missing_optional_account_id_is_not_added_as_a_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "ChatGPT-Account-ID" not in request.headers
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Chunks(_completed_response([{
                "type": "message", "content": [{"type": "output_text", "text": "ok"}],
            }])),
        )

    client = _client(
        handler,
        source=StaticChatGPTCredentialSource(ChatGPTCredentials(TOKEN, None)),
    )
    try:
        assert client.complete([AgentMessage(role="user", content="hi")], []).content == "ok"
    finally:
        client._client.close()


@pytest.mark.parametrize("status_code", [401, 403])
def test_codex_auth_http_failure_is_redacted_and_does_not_refresh_or_rewrite(
    tmp_path: Path,
    status_code: int,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": TOKEN, "account_id": ACCOUNT,
                   "refresh_token": "must-never-be-used"},
    }))
    before = auth_file.read_bytes()
    gets = 0

    class CountingSource(CodexAuthFileCredentialSource):
        def get(self):
            nonlocal gets
            gets += 1
            return super().get()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["ChatGPT-Account-ID"] == ACCOUNT
        return httpx.Response(
            status_code,
            json={"error": {"code": "auth_failed", "message": f"bad {TOKEN} {ACCOUNT}"}},
        )

    client = _client(handler, source=CountingSource(auth_file), retries=2)
    try:
        with pytest.raises(ProviderRequestError) as raised:
            client.complete([AgentMessage(role="user", content="hello")], [])
    finally:
        client.close()

    assert gets == 1
    assert TOKEN not in str(raised.value)
    assert ACCOUNT not in str(raised.value)
    assert "auth_failed" in str(raised.value)
    assert auth_file.read_bytes() == before


@pytest.mark.parametrize(
    ("model", "parallel_tool_calls"),
    [
        ("gpt-6-luna", True),
        ("gpt-test", False),
        ("gpt-5.6-sol", False),
    ],
)
def test_model_capabilities_preserve_evidence_and_default_conservatively(
    model: str,
    parallel_tool_calls: bool,
) -> None:
    transport = httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(500)
    ))
    client = ChatGPTCodexLLMClient(
        ChatGPTCodexConfig(model=model),
        credential_source=StaticChatGPTCredentialSource(
            ChatGPTCredentials(TOKEN, ACCOUNT)
        ),
        client=transport,
    )
    try:
        payload = client._request_payload(
            [AgentMessage(role="user", content="Use the lookup tool")],
            [ToolDefinition(
                name="lookup_item",
                description="Look up a synthetic item",
                input_schema={"type": "object", "properties": {}},
            )],
        )
        assert payload["parallel_tool_calls"] is parallel_tool_calls
        assert client.info.config["parallel_tool_calls"] is parallel_tool_calls
    finally:
        transport.close()


def test_http_error_does_not_expose_token_prefix_at_detail_limit() -> None:
    boundary_token = "unique-token-prefix-then-secret-suffix"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": {
            "message": "x" * 985 + boundary_token,
        }})

    client = _client(handler, source=StaticChatGPTCredentialSource(
        ChatGPTCredentials(boundary_token, None)
    ))
    try:
        with pytest.raises(ProviderRequestError) as raised:
            client.complete([AgentMessage(role="user", content="hi")], [])
    finally:
        client.close()
    assert "unique-token" not in str(raised.value)


def test_request_maps_generic_history_and_tools_to_codex_responses() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Chunks(_completed_response([{
                "type": "message", "content": [{"type": "output_text", "text": "Found it."}],
            }])),
        )

    messages = [
        AgentMessage(role="system", content="System instructions"),
        AgentMessage(role="user", content="Where is the cable?"),
        AgentMessage(
            role="assistant",
            content="I will look.",
            tool_calls=(ToolCall(id="call_old", name="lookup_item", arguments={"name": "cable"}),),
        ),
        AgentMessage(role="tool", content='{"location":"box"}', tool_call_id="call_old", tool_name="lookup_item"),
        AgentMessage(role="assistant", content="Now answer."),
    ]
    tools = [ToolDefinition(
        name="lookup_item", description="Look up an item", input_schema={
            "type": "object", "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )]
    client = _client(handler)
    try:
        result = client.complete(messages, tools)
    finally:
        client.close()

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-test"
    assert body["instructions"] == "System instructions"
    assert body["store"] is False and body["stream"] is True
    assert body["tool_choice"] == "auto"
    assert body["input"][0]["role"] == "user"
    assert body["input"][1] == {
        "role": "assistant", "content": [{"type": "output_text", "text": "I will look."}],
    }
    assert body["input"][2] == {
        "type": "function_call", "call_id": "call_old", "name": "lookup_item",
        "arguments": '{"name":"cable"}',
    }
    assert body["input"][3] == {
        "type": "function_call_output", "call_id": "call_old", "output": '{"location":"box"}',
    }
    assert body["tools"][0]["parameters"] == tools[0].input_schema
    assert TOKEN not in json.dumps(body)
    assert ACCOUNT not in json.dumps(body)
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert headers["chatgpt-account-id"] == ACCOUNT
    assert result.content == "Found it."
    assert result.tool_calls == ()
    assert TOKEN not in repr(client.info)


def test_direct_adapter_rejects_unknown_returned_tool_name() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Chunks(_completed_response([{
                "type": "function_call", "call_id": "call_1",
                "name": "drop_inventory", "arguments": "{}",
            }])),
        )

    client = _client(handler)
    try:
        with pytest.raises(ProviderProtocolError, match="unknown tool"):
            client.complete([AgentMessage(role="user", content="hi")], [
                ToolDefinition(name="lookup_item", description="test", input_schema={"type": "object"}),
            ])
    finally:
        client._client.close()


def test_sse_parser_handles_fragmentation_comments_text_and_multiple_calls() -> None:
    events = b": comment\n\n" + b"".join([
        _sse_event("response.output_text.delta", {"type": "response.output_text.delta", "delta": "partial"}),
        _sse_event("response.output_item.added", {"type": "response.output_item.added", "item": {
            "id": "item_1", "call_id": "call_1", "type": "function_call",
            "name": "lookup_item", "arguments": "",
        }}),
        _sse_event("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": "item_1", "delta": '{"name":'}),
        _sse_event("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": "item_1", "delta": '"cable"}'}),
        _sse_event("response.output_item.done", {"type": "response.output_item.done", "item": {
            "id": "item_1", "call_id": "call_1", "type": "function_call",
            "name": "lookup_item", "arguments": '{"name":"cable"}',
        }}),
        _completed_response([
            {"type": "message", "content": [{"type": "output_text", "text": "final"}]},
            {"type": "function_call", "call_id": "call_1", "name": "lookup_item", "arguments": '{"name":"cable"}'},
            {"type": "function_call", "call_id": "call_2", "name": "lookup_item", "arguments": '{"name":"key"}'},
        ]),
    ])
    chunks = [events[:13], events[13:89], events[89:220], events[220:]]

    result = parse_responses_sse(chunks)

    assert result["content"] == "final"
    assert result["response_id"] == "resp_1"
    assert [call.id for call in result["tool_calls"]] == ["call_1", "call_2"]
    assert result["tool_calls"][0].arguments == {"name": "cable"}
    assert result["tool_calls"][1].arguments == {"name": "key"}


def test_sse_uses_incremental_tool_arguments_when_completed_output_is_empty() -> None:
    events = b"".join([
        _sse_event("response.output_item.added", {"type": "response.output_item.added", "item": {
            "id": "item_1", "call_id": "call_1", "type": "function_call",
            "name": "lookup_item", "arguments": "",
        }}),
        _sse_event("response.function_call_arguments.delta", {"type": "response.function_call_arguments.delta", "item_id": "item_1", "delta": '{"name":"cable"}'}),
        _completed_response([]),
    ])

    result = parse_responses_sse([events])

    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0].id == "call_1"
    assert result["tool_calls"][0].arguments == {"name": "cable"}


@pytest.mark.parametrize("chunks, message", [
    ([b"data: {nope}\n\n"], "malformed"),
    ([b"data: {\"type\":\"response.output_text.delta\",\"delta\":\"hi\"}\n\n"], "before completion"),
])
def test_sse_malformed_and_premature_eof_fail_closed(chunks, message: str) -> None:
    with pytest.raises(ProviderProtocolError, match=message):
        parse_responses_sse(chunks)


def test_sse_oversized_tool_arguments_and_stream_error_are_bounded_and_safe() -> None:
    with pytest.raises(ProviderProtocolError, match="size limit"):
        parse_responses_sse([b"x" * 20], max_bytes=10)

    incomplete = _sse_event("response.output_item.added", {"type": "response.output_item.added", "item": {
        "id": "item_1", "call_id": "call_1", "type": "function_call",
        "name": "lookup_item", "arguments": "{bad",
    }}) + _sse_event("response.completed", {"type": "response.completed", "response": {
        "id": "resp_1", "status": "completed",
    }})
    with pytest.raises(ProviderProtocolError, match="function arguments"):
        parse_responses_sse([incomplete])

    error = _sse_event("error", {"type": "error", "error": {
        "code": "rejected", "message": f"credential {TOKEN}; account {ACCOUNT}",
    }})
    with pytest.raises(ProviderRequestError) as raised:
        parse_responses_sse([error], secrets=(TOKEN, ACCOUNT))
    assert TOKEN not in str(raised.value)
    assert ACCOUNT not in str(raised.value)


def test_sse_error_does_not_expose_token_prefix_at_detail_limit() -> None:
    boundary_token = "unique-token-prefix-then-secret-suffix"
    error = _sse_event("error", {"type": "error", "error": {
        "message": "x" * 985 + boundary_token,
    }})
    with pytest.raises(ProviderRequestError) as raised:
        parse_responses_sse([error], secrets=(boundary_token,))
    assert "unique-token" not in str(raised.value)


def test_direct_stream_has_an_overall_elapsed_time_limit() -> None:
    class SlowChunks(httpx.SyncByteStream):
        def __iter__(self):
            time.sleep(0.03)
            yield _completed_response([{
                "type": "message", "content": [{"type": "output_text", "text": "late"}],
            }])

    http = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
        200, stream=SlowChunks(),
    )))
    client = ChatGPTCodexLLMClient(
        ChatGPTCodexConfig(model="gpt-test", timeout_seconds=0.01, max_retries=0),
        credential_source=StaticChatGPTCredentialSource(ChatGPTCredentials(TOKEN, ACCOUNT)),
        client=http,
    )
    try:
        with pytest.raises(ProviderRequestError, match="timed out"):
            client.complete([AgentMessage(role="user", content="hi")], [])
    finally:
        http.close()


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_does_not_retry_or_refresh(status: int) -> None:
    calls = 0

    def unauthorized(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "unauthorized"}})

    client = _client(unauthorized, retries=2)
    try:
        with pytest.raises(ProviderRequestError, match=f"HTTP {status}"):
            client.complete([AgentMessage(role="user", content="hi")], [])
    finally:
        client.close()
    assert calls == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_status_can_retry(status: int) -> None:
    calls = 0

    def transient_then_ok(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(status, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=Chunks(_completed_response([])),
        )

    client = _client(transient_then_ok, retries=1)
    try:
        assert client.complete([AgentMessage(role="user", content="hi")], []).content == ""
    finally:
        client.close()
    assert calls == 2


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ConnectError])
def test_timeout_and_connection_errors_are_bounded_and_redacted(failure) -> None:
    def broken(_request: httpx.Request) -> httpx.Response:
        raise failure(f"upstream echoed {TOKEN}")

    client = _client(broken, retries=0)
    try:
        with pytest.raises(ProviderRequestError) as raised:
            client.complete([AgentMessage(role="user", content="hi")], [])
    finally:
        client.close()
    assert TOKEN not in str(raised.value)
