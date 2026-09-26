"""Application configuration and factory integration for ChatGPT/Codex."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from ah_there_it_is.agent import factory as factory_module
from ah_there_it_is.agent.chatgpt_codex import ChatGPTCodexLLMClient
from ah_there_it_is.agent.errors import ProviderRequestError
from ah_there_it_is.agent.protocol import AgentMessage
from ah_there_it_is.config import Settings, get_settings


ACCESS_ONE = "factory-test-access-one"
ACCESS_TWO = "factory-test-access-two"
ACCOUNT = "factory-test-account"


def _completed_text(text: str) -> bytes:
    event = {
        "type": "response.completed",
        "response": {
            "id": "factory-response",
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }],
        },
    }
    return f"event: response.completed\ndata: {json.dumps(event)}\n\n".encode()


def _write_auth_cache(path: Path, access_token: str) -> bytes:
    path.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": access_token, "account_id": ACCOUNT},
    }))
    return path.read_bytes()


def test_environment_selects_chatgpt_codex_and_model_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AH_THERE_IT_IS_ENV", "development")
    monkeypatch.setenv("AH_THERE_IT_IS_LLM_PROVIDER", "chatgpt-codex")
    monkeypatch.setenv("AH_THERE_IT_IS_LLM_MODEL", "gpt-6-luna")
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.llm_provider == "chatgpt-codex"
    assert settings.llm_model == "gpt-6-luna"
    assert settings.llm_api_key is None
    assert "chatgpt_access_token" not in Settings.model_fields


@pytest.mark.parametrize("model", [None, "", "   "])
def test_factory_requires_an_explicit_nonempty_model(model: str | None) -> None:
    with pytest.raises(ValueError, match="AH_THERE_IT_IS_LLM_MODEL is required"):
        factory_module.build_llm_factory(Settings(
            llm_provider="chatgpt-codex",
            llm_model=model,
        ))


def test_factory_constructs_direct_adapter_with_safe_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def reject_send(_client, request, *args, **kwargs):
        calls.append(str(request.url))
        raise AssertionError("provider construction must not perform network requests")

    monkeypatch.setattr(httpx.Client, "send", reject_send)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    factory = factory_module.build_llm_factory(Settings(
        llm_provider="chatgpt-codex",
        llm_model="gpt-6-luna",
        llm_api_key="unrelated-platform-key",
    ))
    client = factory()
    try:
        assert isinstance(client, ChatGPTCodexLLMClient)
        info = client.info.model_dump()
        assert info["provider"] == "chatgpt-codex"
        assert info["model"] == "gpt-6-luna"
        assert info["config"]["parallel_tool_calls"] is True
        assert "unrelated-platform-key" not in json.dumps(info)
        assert calls == []
    finally:
        client.close()


def test_factory_rereads_replaced_auth_cache_and_uses_only_direct_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "auth.json"
    first_cache = _write_auth_cache(auth_file, ACCESS_ONE)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    requests: list[tuple[str, str, dict]] = []
    texts = iter(("first reply", "second reply"))

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append((
            str(request.url),
            request.headers["authorization"],
            json.loads(request.content),
        ))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_completed_text(next(texts)),
        )

    adapter_type = factory_module.ChatGPTCodexLLMClient

    def injected_adapter(config):
        return adapter_type(
            config,
            client=httpx.Client(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(factory_module, "ChatGPTCodexLLMClient", injected_adapter)
    settings = Settings(
        llm_provider="chatgpt-codex",
        llm_model="gpt-6-luna",
        llm_api_key="unrelated-platform-key",
        llm_max_retries=0,
    )
    client = factory_module.build_llm_factory(settings)()
    environment_before = dict(os.environ)
    try:
        first = client.complete([AgentMessage(role="user", content="Say first")], [])
        assert auth_file.read_bytes() == first_cache
        second_cache = _write_auth_cache(auth_file, ACCESS_TWO)
        second = client.complete([AgentMessage(role="user", content="Say second")], [])
        assert auth_file.read_bytes() == second_cache
    finally:
        client.close()

    assert first.content == "first reply"
    assert second.content == "second reply"
    assert [request[0] for request in requests] == [
        "https://chatgpt.com/backend-api/codex/responses",
        "https://chatgpt.com/backend-api/codex/responses",
    ]
    assert [request[1] for request in requests] == [
        f"Bearer {ACCESS_ONE}", f"Bearer {ACCESS_TWO}",
    ]
    assert all("unrelated-platform-key" not in json.dumps(request[2]) for request in requests)
    assert dict(os.environ) == environment_before
    assert not any(secret in json.dumps(client.info.model_dump()) for secret in (
        ACCESS_ONE, ACCESS_TWO, ACCOUNT, "unrelated-platform-key",
    ))


def test_factory_client_reports_missing_auth_cache_without_secret_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    client = factory_module.build_llm_factory(Settings(
        llm_provider="chatgpt-codex",
        llm_model="gpt-6-luna",
        llm_max_retries=0,
    ))()
    try:
        with pytest.raises(ProviderRequestError, match="credentials are unavailable") as raised:
            client.complete([AgentMessage(role="user", content="Say OK")], [])
    finally:
        client.close()

    assert ACCESS_ONE not in str(raised.value)
    assert ACCOUNT not in str(raised.value)
