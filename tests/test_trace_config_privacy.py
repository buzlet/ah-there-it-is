# test_trace_config_privacy.py
"""New provider traces retain stable metadata without request secrets."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient
from ah_there_it_is.agent.errors import ProviderRequestError
from ah_there_it_is.agent.gemini import GeminiConfig, GeminiLLMClient
from ah_there_it_is.agent.openai_compatible import (
    OpenAICompatibleConfig, OpenAICompatibleLLMClient,
)
from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import AgentRunLog
from ah_there_it_is.services.chat_application import ChatApplicationService
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.services.evaluation import EvaluationService


class _SessionContext:
    def __init__(self, session: Session) -> None:
        self.session = session

    def __enter__(self) -> Session:
        return self.session

    def __exit__(self, *_args) -> None:
        return None


def test_openai_trace_config_excludes_url_and_nested_request_secrets(session: Session) -> None:
    request_bodies: list[dict] = []
    def respond(request: httpx.Request) -> httpx.Response:
        request_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"finish_reason": "stop", "message": {"content": "Done."}}],
        })

    run_ids = []
    secrets = []
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        for suffix in ("one", "two"):
            secrets.extend((f"password-{suffix}", f"query-{suffix}",
                            f"fragment-{suffix}", f"nested-{suffix}", f"api-{suffix}"))
            adapter = OpenAICompatibleLLMClient(
                OpenAICompatibleConfig(
                    base_url=(f"https://user:password-{suffix}@provider.example/v1"
                              f"?token=query-{suffix}#fragment-{suffix}"),
                    model="test-model", api_key=f"api-{suffix}",
                    temperature=0.2, extra_body={"nested": {"secret": f"nested-{suffix}"}},
                ),
                client=transport,
            )
            run_ids.append(AgentRunner(session, adapter).run("Hello").run_id)

    assert [body["nested"]["secret"] for body in request_bodies] == [
        "nested-one", "nested-two",
    ]
    evaluation = EvaluationService(session)
    configs = [evaluation.get_run(run_id).llm_config for run_id in run_ids]
    assert configs[0] == configs[1]
    assert configs[0]["base_url"] == "https://provider.example/v1"
    assert configs[0]["has_extra_body"] is True
    assert configs[0]["temperature"] == 0.2
    assert "extra_body" not in configs[0]
    assert len(evaluation.summaries()) == 1
    serialized = json.dumps([evaluation.get_run(run_id).llm_config for run_id in run_ids])
    assert not any(secret in serialized for secret in secrets)

    app = create_app(
        Settings(app_name="Trace Privacy"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    )
    with TestClient(app) as web:
        detail = web.get(f"/evaluations/{run_ids[0]}")
        summary = web.get("/evaluations")
    assert detail.status_code == 200 and summary.status_code == 200
    assert "https://provider.example/v1" in detail.text
    assert not any(secret in detail.text or secret in summary.text for secret in secrets)


def test_gemini_trace_config_excludes_secrets_but_request_keeps_extra_body() -> None:
    adapter = GeminiLLMClient(GeminiConfig(
        model="gemini-test", api_key="api-gemini-secret",
        base_url="https://user:password-gemini@provider.example/v1beta?key=query-gemini#fragment-gemini",
        temperature=0.4,
        extra_body={"nested": {"secret": "nested-gemini"}},
    ))
    captured: list[tuple[dict, dict]] = []
    def respond(payload: bytes, headers: dict) -> bytes:
        captured.append((json.loads(payload), headers))
        return json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Done."}]},
                            "finishReason": "STOP"}],
        }).encode()
    adapter._post_with_retry = respond  # type: ignore[method-assign]
    from ah_there_it_is.agent.protocol import AgentMessage
    assert adapter.complete([AgentMessage(role="user", content="Hello")], []).content == "Done."
    assert captured[0][0]["nested"]["secret"] == "nested-gemini"
    assert captured[0][1]["X-goog-api-key"] == "api-gemini-secret"
    config = adapter.info.config
    assert config["base_url"] == "https://provider.example/v1beta"
    assert config["has_extra_body"] is True
    assert config["temperature"] == 0.4
    serialized = json.dumps(adapter.info.model_dump())
    secrets = (
        "password-gemini", "query-gemini", "fragment-gemini",
        "nested-gemini", "api-gemini-secret",
    )
    for secret in secrets:
        assert secret not in serialized
    safe_error = adapter._safe_error_detail("provider echoed " + " ".join(secrets))
    assert not any(secret in safe_error for secret in secrets)
    assert "[redacted]" in safe_error


def test_historical_config_shape_remains_readable(session: Session) -> None:
    run_id = AgentRunner(session, ScriptedLLMClient([LLMResponse(content="Done.")])).run("Hello").run_id
    evaluation = EvaluationService(session)
    run = evaluation.get_run(run_id)
    run.llm_config = {"extra_body": {"legacy": "historical-value"}}
    session.commit()
    assert evaluation.summaries()[0].llm_config == run.llm_config
    app = create_app(
        Settings(app_name="Legacy Trace"),
        session_factory=lambda: _SessionContext(session),  # type: ignore[arg-type]
    )
    with TestClient(app) as web:
        detail = web.get(f"/evaluations/{run_id}")
    assert detail.status_code == 200
    assert "historical-value" in detail.text


def test_provider_error_redacts_config_secrets_before_durable_failure_evidence(
    session: Session,
) -> None:
    secrets = (
        "TEST_API_SECRET_0087",
        "TEST_PASSWORD_SECRET_0087",
        "TEST_QUERY_SECRET_0087",
        "TEST_FRAGMENT_SECRET_0087",
        "TEST_NESTED_SECRET_0087",
    )

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="denied " + " ".join(secrets))

    config = OpenAICompatibleConfig(
        base_url=(
            "https://user:TEST_PASSWORD_SECRET_0087@provider.example/v1"
            "?token=TEST_QUERY_SECRET_0087#TEST_FRAGMENT_SECRET_0087"
        ),
        model="test-model",
        api_key=secrets[0],
        extra_body={"nested": {"secret": secrets[-1]}},
        max_retries=0,
    )
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        service = ChatApplicationService(
            session,
            lambda: OpenAICompatibleLLMClient(config, client=transport),
        )
        with pytest.raises(ProviderRequestError) as error:
            service.execute_chat(
                "Trigger provider failure",
                request_key="provider-failure-0087",
                source_identity="web",
            )

    run = session.scalar(select(AgentRunLog).order_by(AgentRunLog.id.desc()).limit(1))
    record = ChatRequestService(session).get("provider-failure-0087")
    assert run is not None and run.status == "failed"
    assert record is not None and record.status == "failed"
    evidence = json.dumps(
        {
            "exception": str(error.value),
            "run_error": run.error,
            "tool_trace": run.tool_trace,
            "receipts": run.mutation_receipts,
            "request_error": record.error,
            "source_identity": record.source_identity,
        },
        ensure_ascii=False,
    )
    assert not any(secret in evidence for secret in secrets)
    assert "[redacted]" in evidence
