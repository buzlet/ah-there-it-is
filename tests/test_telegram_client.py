from __future__ import annotations

import json

import httpx
import pytest

from ah_there_it_is.telegram.client import (
    MAX_TELEGRAM_TEXT_LENGTH,
    TelegramApiError,
    TelegramBotClient,
    TelegramResponseError,
    TelegramTransportError,
)


def _message(message_id: int, text: str = "ok") -> dict:
    return {
        "message_id": message_id,
        "chat": {"id": 99, "type": "private"},
        "from": {"id": 7},
        "text": text,
    }


def test_get_updates_uses_offset_and_parses_only_adapter_fields() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path.endswith("/botsecret/getUpdates")
        assert request.read() and json.loads(request.content) == {
            "offset": 11,
            "timeout": 5,
            "limit": 2,
        }
        return httpx.Response(
            200,
            json={"ok": True, "result": [{"update_id": 12, "message": _message(3, "hello")}]},
        )

    with TelegramBotClient(
        "secret", base_url="https://telegram.test", transport=httpx.MockTransport(respond)
    ) as client:
        updates = client.get_updates(offset=11, timeout=5, limit=2)

    assert len(seen) == 1
    assert updates[0].update_id == 12
    assert updates[0].message is not None
    assert updates[0].message.chat.type == "private"
    assert updates[0].message.from_user is not None
    assert updates[0].message.from_user.id == 7
    assert updates[0].message.text == "hello"


def test_send_message_splits_at_one_isolated_limit() -> None:
    bodies: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        index = len(bodies)
        return httpx.Response(200, json={"ok": True, "result": _message(index)})

    text = "a" * (MAX_TELEGRAM_TEXT_LENGTH + 3)
    with TelegramBotClient(
        "secret", base_url="https://telegram.test", transport=httpx.MockTransport(respond)
    ) as client:
        sent = client.send_message(99, text)

    assert len(sent) == 2
    assert b'"text":"' + (b"a" * MAX_TELEGRAM_TEXT_LENGTH) in bodies[0]
    assert b'"text":"aaa"' in bodies[1]
    assert [message.message_id for message in sent] == [1, 2]


def test_client_retries_transient_http_failure_with_bounded_backoff() -> None:
    attempts = 0
    sleeps: list[float] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": []})

    with TelegramBotClient(
        "secret",
        base_url="https://telegram.test",
        max_retries=2,
        backoff_seconds=0.25,
        sleep=sleeps.append,
        transport=httpx.MockTransport(respond),
    ) as client:
        assert client.get_updates(timeout=0) == []

    assert attempts == 2
    assert sleeps == [0.25]


def test_malformed_and_ok_false_errors_never_expose_token() -> None:
    token = "secret-token"

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    with TelegramBotClient(
        token, base_url="https://telegram.test", transport=httpx.MockTransport(malformed)
    ) as client:
        with pytest.raises(TelegramResponseError, match="omitted result") as error:
            client.get_updates(timeout=0)
    assert token not in str(error.value)

    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": 401, "description": f"bad {token}"},
        )

    with TelegramBotClient(
        token, base_url="https://telegram.test", transport=httpx.MockTransport(rejected)
    ) as client:
        with pytest.raises(TelegramApiError) as error:
            client.get_updates(timeout=0)
    assert token not in str(error.value)
    assert "[redacted]" in str(error.value)


def test_transport_retry_exhaustion_is_bounded_and_token_safe() -> None:
    token = "secret-token"
    attempts = 0

    def fail(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("connection failed", request=request)

    with TelegramBotClient(
        token,
        base_url="https://telegram.test",
        max_retries=2,
        backoff_seconds=0,
        transport=httpx.MockTransport(fail),
    ) as client:
        with pytest.raises(TelegramTransportError) as error:
            client.get_updates(timeout=0)
    assert attempts == 3
    assert token not in str(error.value)
