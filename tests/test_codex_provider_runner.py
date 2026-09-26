"""Synthetic AgentRunner compatibility for the standalone provider."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner
from ah_there_it_is.agent.chatgpt_codex import ChatGPTCodexConfig, ChatGPTCodexLLMClient
from ah_there_it_is.agent.codex_credentials import (
    ChatGPTCredentials,
    StaticChatGPTCredentialSource,
)
from ah_there_it_is.agent.errors import AgentLoopLimitError, ProviderRequestError
from ah_there_it_is.agent.protocol import AgentMessage
from ah_there_it_is.services import InventoryService
from ah_there_it_is.services.evaluation import EvaluationService


TOKEN = "runner-fake-access-secret"


def _event(data: dict) -> bytes:
    return f"event: response.completed\ndata: {json.dumps(data)}\n\n".encode()


def _call(call_id: str, name: str, arguments: dict) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=_event({
            "type": "response.completed",
            "response": {
                "id": f"resp_{call_id}",
                "status": "completed",
                "output": [{
                    "type": "function_call",
                    "call_id": call_id,
                    "name": name,
                    "arguments": json.dumps(arguments),
                }],
            },
        }),
    )


def _text(response_id: str, content: str) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=_event({
            "type": "response.completed",
            "response": {
                "id": response_id,
                "status": "completed",
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": content}],
                }],
            },
        }),
    )


def _provider(handler, requests: list[dict]):
    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return handler(request)

    return ChatGPTCodexLLMClient(
        ChatGPTCodexConfig(model="gpt-test", max_retries=0),
        credential_source=StaticChatGPTCredentialSource(
            ChatGPTCredentials(TOKEN, "runner-fake-account")
        ),
        client=httpx.Client(transport=httpx.MockTransport(capture)),
    )


def test_runner_receives_tool_call_and_full_history_on_next_round(session: Session) -> None:
    InventoryService(session).create_item("Probe cable")
    requests: list[dict] = []
    responses = [
        _call("search_1", "search_items", {"query": "Probe cable"}),
        _text("resp_final", "Нашёл предмет Probe cable."),
    ]
    provider = _provider(lambda _request: responses.pop(0), requests)
    try:
        result = AgentRunner(session, provider, system_prompt="synthetic runner test").run(
            "Найди Probe cable"
        )
    finally:
        provider._client.close()

    assert result.rounds == 2
    assert result.content == "Нашёл предмет Probe cable."
    assert any(
        item.get("type") == "function_call"
        for item in requests[1]["input"]
    )
    assert any(
        item.get("type") == "function_call_output"
        for item in requests[1]["input"]
    )
    trace = EvaluationService(session).get_run(result.run_id)
    assert trace.llm_provider == "chatgpt-codex"
    assert trace.llm_model == "gpt-test"
    assert "provider_state" not in json.dumps(trace.tool_trace)
    assert TOKEN not in json.dumps(trace.llm_config)
    assert "runner-fake-account" not in json.dumps(trace.llm_config)
    assert trace.tool_trace[0]["assistant"]["tool_calls"][0]["name"] == "search_items"


def test_runner_max_round_limit_still_applies_to_adapter(session: Session) -> None:
    requests: list[dict] = []
    provider = _provider(
        lambda _request: _call("search_loop", "search_items", {"query": "none"}),
        requests,
    )
    try:
        with pytest.raises(AgentLoopLimitError):
            AgentRunner(session, provider, max_rounds=1).run("Найди none")
    finally:
        provider._client.close()

    failed_runs = EvaluationService(session).recent_runs(limit=1)
    assert failed_runs[0].status == "failed"
    assert failed_runs[0].rounds == 1
    assert len(requests) == 1


def test_provider_failure_rolls_back_prior_tool_mutation(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Probe cable")
    shelf = inventory.create_location("Probe shelf")
    requests: list[dict] = []
    results = [
        _call("search_item", "search_items", {"query": "Probe cable"}),
        _call("search_shelf", "search_locations", {"query": "Probe shelf"}),
        _call("move", "move_item", {"item_id": item.id, "location_id": shelf.id}),
        httpx.Response(
            401,
            json={"error": {"code": "unauthorized", "message": f"rejected {TOKEN}"}},
        ),
    ]
    provider = _provider(lambda _request: results.pop(0), requests)
    try:
        with pytest.raises(ProviderRequestError) as raised:
            AgentRunner(session, provider).run(
                "Перемести Probe cable на Probe shelf"
            )
    finally:
        provider._client.close()

    assert TOKEN not in str(raised.value)
    assert inventory.get_item(item.id).current_location_id is None
    failed_runs = EvaluationService(session).recent_runs(limit=1)
    assert failed_runs[0].status == "failed"
    assert failed_runs[0].tool_trace[2]["tool_results"][0]["tool_name"] == "move_item"
    assert failed_runs[0].tool_trace[2]["tool_results"][0]["result"]["commit_state"] == "rolled_back"
