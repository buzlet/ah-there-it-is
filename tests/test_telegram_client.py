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


def test_malformed_api_error_code_cannot_expose_bot_token() -> None:
    token = "TEST_SECRET_DO_NOT_PERSIST_7391"

    def rejected(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": f"401 {token}", "description": "denied"},
        )

    with TelegramBotClient(
        token, base_url="https://telegram.test", transport=httpx.MockTransport(rejected)
    ) as client:
        with pytest.raises(TelegramApiError) as error:
            client.get_updates(timeout=0)
    assert token not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"update_id": True},
        {"update_id": -1},
        {"update_id": 9_223_372_036_854_775_807},
        {"update_id": 1, "message": {"message_id": True, "chat": {"id": 7, "type": "private"}, "from": {"id": 7}, "text": "hi"}},
        {"update_id": 1, "message": {"message_id": 1, "chat": {"id": True, "type": "private"}, "from": {"id": 7}, "text": "hi"}},
        {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 7, "type": "private"}, "from": {"id": True}, "text": "hi"}},
    ],
)
def test_invalid_ids_are_malformed_telegram_updates(payload: dict) -> None:
    with pytest.raises(TelegramResponseError):
        TelegramBotClient._parse_update(payload)


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


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"bot_token": ""}, "bot token"),
        ({"bot_token": "secret", "timeout_seconds": 0}, "timeout_seconds"),
        ({"bot_token": "secret", "timeout_seconds": 301}, "timeout_seconds"),
        ({"bot_token": "secret", "max_retries": -1}, "max_retries"),
        ({"bot_token": "secret", "max_retries": 6}, "max_retries"),
        ({"bot_token": "secret", "backoff_seconds": -1}, "backoff_seconds"),
        ({"bot_token": "secret", "backoff_seconds": 31}, "backoff_seconds"),
    ],
)
def test_client_rejects_invalid_configuration(kwargs, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        TelegramBotClient(**kwargs)


def test_client_rejects_invalid_request_limits_and_message_arguments() -> None:
    with TelegramBotClient(
        "secret",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"ok": True, "result": []})),
    ) as client:
        with pytest.raises(ValueError, match="timeout"):
            client.get_updates(timeout=51)
        with pytest.raises(ValueError, match="limit"):
            client.get_updates(limit=0)
        with pytest.raises(ValueError, match="chat_id"):
            client.send_message(True, "text")
        with pytest.raises(ValueError, match="text"):
            client.send_message(7, "")


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, TelegramApiError), (500, TelegramApiError), (400, TelegramApiError)],
)
def test_http_status_failures_are_classified_without_retry(status: int, error) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"ok": False})

    with TelegramBotClient(
        "secret",
        max_retries=0,
        transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(error):
            client.get_updates(timeout=0)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"ok": "yes", "result": []}),
        httpx.Response(200, json={"ok": True, "result": {}}),
    ],
)
def test_malformed_response_shapes_are_rejected(response: httpx.Response) -> None:
    with TelegramBotClient(
        "secret",
        max_retries=0,
        transport=httpx.MockTransport(lambda _request: response),
    ) as client:
        with pytest.raises(TelegramResponseError):
            client.get_updates(timeout=0)


def test_retry_after_malformed_payload_is_ignored_and_update_shapes_are_checked() -> None:
    attempts = 0
    sleeps: list[float] = []

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, content=b"not-json")
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 1}]})

    with TelegramBotClient(
        "secret",
        max_retries=1,
        backoff_seconds=0.1,
        sleep=sleeps.append,
        transport=httpx.MockTransport(respond),
    ) as client:
        updates = client.get_updates(timeout=0)
    assert updates[0].message is None
    assert sleeps == [0.1]

    for malformed in (None, {}, {"update_id": "bad"}):
        with pytest.raises(TelegramResponseError):
            TelegramBotClient._parse_update(malformed)
    for malformed in (
        None,
        {},
        {"message_id": "bad", "chat": {}},
        {"message_id": 1, "chat": {"id": "bad", "type": "private"}},
        {"message_id": 1, "chat": {"id": 1, "type": "private"}, "from": {"id": "bad"}},
        {"message_id": 1, "chat": {"id": 1, "type": "private"}, "text": 3},
    ):
        with pytest.raises(TelegramResponseError):
            TelegramBotClient._parse_message(malformed)


def test_external_httpx_client_is_not_closed_by_transport_wrapper() -> None:
    http_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True, "result": []})
        )
    )
    wrapper = TelegramBotClient("secret", client=http_client)
    wrapper.close()
    assert http_client.is_closed is False
    http_client.close()
