"""Manual provider smoke coverage through the application factory."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ah_there_it_is.agent import factory as factory_module
from ah_there_it_is.agent.errors import ProviderRequestError
from ah_there_it_is.config import Settings
from ah_there_it_is import provider_smoke


ACCESS = "smoke-test-access-secret"
ACCOUNT = "smoke-test-account-secret"


def _event(text: str) -> bytes:
    data = {
        "type": "response.completed",
        "response": {
            "id": "smoke-response",
            "status": "completed",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }],
        },
    }
    return f"event: response.completed\ndata: {json.dumps(data)}\n\n".encode()


def _inject_factory_transport(monkeypatch, handler) -> None:
    adapter_type = factory_module.ChatGPTCodexLLMClient

    def injected_adapter(config):
        return adapter_type(
            config,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    monkeypatch.setattr(factory_module, "ChatGPTCodexLLMClient", injected_adapter)


def _auth_cache(tmp_path: Path) -> bytes:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        "auth_mode": "chatgpt",
        "tokens": {"access_token": ACCESS, "account_id": ACCOUNT},
    }))
    return auth_file.read_bytes()


def test_smoke_uses_factory_for_bounded_non_tool_text_and_no_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    auth_before = _auth_cache(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    database = tmp_path / "production.db"
    monkeypatch.setattr(provider_smoke, "get_settings", lambda: Settings(
        llm_provider="chatgpt-codex",
        llm_model="gpt-test",
        llm_max_retries=0,
        database_url=f"sqlite:///{database}",
    ))
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_event("OK"),
        )

    _inject_factory_transport(monkeypatch, respond)
    provider_smoke.main()

    output = capsys.readouterr().out
    assert output == "OK\n"
    assert len(requests) == 1
    payload = json.loads(requests[0].content)
    assert payload["model"] == "gpt-test"
    assert "tools" not in payload
    assert "Return the word OK." in json.dumps(payload)
    assert database.exists() is False
    assert (tmp_path / "auth.json").read_bytes() == auth_before


def test_smoke_surfaces_only_redacted_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_before = _auth_cache(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(provider_smoke, "get_settings", lambda: Settings(
        llm_provider="chatgpt-codex",
        llm_model="gpt-test",
        llm_max_retries=0,
    ))

    def reject(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {
            "code": "unauthorized",
            "message": f"rejected {ACCESS} {ACCOUNT}",
        }})

    _inject_factory_transport(monkeypatch, reject)
    with pytest.raises(ProviderRequestError) as raised:
        provider_smoke.main()

    assert "unauthorized" in str(raised.value)
    assert ACCESS not in str(raised.value)
    assert ACCOUNT not in str(raised.value)
    assert (tmp_path / "auth.json").read_bytes() == auth_before


def test_heuristic_smoke_rejection_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_smoke, "get_settings", lambda: Settings())

    def unexpected_factory(_settings):
        raise AssertionError("heuristic smoke must stop before provider construction")

    monkeypatch.setattr(provider_smoke, "build_llm_factory", unexpected_factory)
    with pytest.raises(SystemExit, match="non-heuristic AH_THERE_IT_IS_LLM_PROVIDER"):
        provider_smoke.main()


def test_deployment_docs_describe_safe_post_merge_provider_selection() -> None:
    readme = Path("deploy/README.md").read_text()

    for required in (
        "AH_THERE_IT_IS_LLM_PROVIDER=chatgpt-codex",
        "AH_THERE_IT_IS_LLM_MODEL=<explicit operator-selected model>",
        "CODEX_HOME",
        "must already have a Codex-managed ChatGPT login",
        "does not log in or refresh it",
        "provider calls fail until Codex itself restores its credential state",
        "Public OpenAI Platform API keys are unrelated",
        "`codex exec` is not used by normal application runtime",
        "unreviewed work",
    ):
        assert required in readme
    assert "AH_THERE_IT_IS_CHATGPT_ACCESS_TOKEN" not in readme
