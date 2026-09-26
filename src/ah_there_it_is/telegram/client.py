"""Small, token-safe httpx transport for the Telegram Bot API."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import time
from typing import Any

import httpx


DEFAULT_TELEGRAM_BASE_URL = "https://api.telegram.org"
MAX_TELEGRAM_TEXT_LENGTH = 4096


class TelegramClientError(RuntimeError):
    """Base class for errors raised by the Telegram transport."""


class TelegramTransportError(TelegramClientError):
    """A bounded transport retry budget was exhausted."""


class TelegramApiError(TelegramClientError):
    """Telegram returned an HTTP or ``ok=false`` API response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelegramPermanentError(TelegramApiError):
    """A non-retryable Telegram configuration or API rejection."""


class TelegramConflictError(TelegramApiError):
    """Another poller may currently own this bot (HTTP/API 409)."""


class TelegramResponseError(TelegramClientError):
    """Telegram returned a malformed response shape."""


@dataclass(frozen=True)
class TelegramUser:
    id: int


@dataclass(frozen=True)
class TelegramChat:
    id: int
    type: str


@dataclass(frozen=True)
class TelegramMessage:
    message_id: int
    chat: TelegramChat
    from_user: TelegramUser | None
    text: str | None


@dataclass(frozen=True)
class TelegramUpdate:
    update_id: int
    message: TelegramMessage | None


class TelegramBotClient:
    """Transport only; policy and accepted-message filtering belong to the adapter."""

    def __init__(
        self,
        bot_token: str,
        *,
        base_url: str = DEFAULT_TELEGRAM_BASE_URL,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.2,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(bot_token, str) or not bot_token.strip():
            raise ValueError("bot token must not be blank")
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("timeout_seconds must be between 0 and 300")
        if max_retries < 0 or max_retries > 5:
            raise ValueError("max_retries must be between 0 and 5")
        if backoff_seconds < 0 or backoff_seconds > 30:
            raise ValueError("backoff_seconds must be between 0 and 30")
        self._token = bot_token.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=self.timeout, transport=transport)

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
        limit: int = 100,
    ) -> list[TelegramUpdate]:
        if timeout < 0 or timeout > 50:
            raise ValueError("timeout must be between 0 and 50")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        payload: dict[str, Any] = {"timeout": timeout, "limit": limit}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramResponseError("Telegram getUpdates result was malformed")
        return [self._parse_update(value) for value in result]

    def send_message(self, chat_id: int, text: str) -> tuple[TelegramMessage, ...]:
        """Send plain text, splitting deterministically at the isolated limit."""
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            raise ValueError("chat_id must be an integer")
        if not isinstance(text, str) or not text:
            raise ValueError("text must not be empty")
        chunks = tuple(
            text[index : index + MAX_TELEGRAM_TEXT_LENGTH]
            for index in range(0, len(text), MAX_TELEGRAM_TEXT_LENGTH)
        )
        messages: list[TelegramMessage] = []
        for chunk in chunks:
            result = self._call(
                "sendMessage",
                {"chat_id": chat_id, "text": chunk},
            )
            messages.append(self._parse_message(result))
        return tuple(messages)

    send_text = send_message

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TelegramBotClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _call(self, method: str, payload: Mapping[str, Any]) -> Any:
        url = f"{self.base_url}/bot{self._token}/{method}"
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(url, json=dict(payload), timeout=self.timeout)
            except httpx.RequestError as exc:
                if attempt >= self.max_retries:
                    raise TelegramTransportError(
                        f"Telegram transport failed ({type(exc).__name__})"
                    ) from None
                self._backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    self._backoff(attempt, response)
                    continue
                if response.status_code == 429:
                    raise TelegramApiError(
                        "Telegram API rate limit response", status_code=429
                    )
                raise TelegramApiError(
                    f"Telegram HTTP error status={response.status_code}",
                    status_code=response.status_code,
                )
            if response.status_code >= 400:
                error_class = self._error_class(response.status_code)
                raise error_class(
                    f"Telegram HTTP error status={response.status_code}",
                    status_code=response.status_code,
                )
            try:
                body = response.json()
            except ValueError:
                raise TelegramResponseError("Telegram response was not valid JSON") from None
            if not isinstance(body, dict) or not isinstance(body.get("ok"), bool):
                raise TelegramResponseError("Telegram response envelope was malformed")
            if body["ok"] is not True:
                code = body.get("error_code")
                description = self._safe_description(body.get("description"))
                # API error codes are integers. Never interpolate an arbitrary
                # response field into an exception: it may contain the bot token.
                safe_code = code if type(code) is int else None
                detail = f"Telegram API returned ok=false{f' code={safe_code}' if safe_code is not None else ''}"
                if description:
                    detail += f": {description}"
                error_class = self._error_class(safe_code)
                raise error_class(detail, status_code=safe_code)
            if "result" not in body:
                raise TelegramResponseError("Telegram response omitted result")
            return body["result"]
        raise TelegramTransportError("Telegram transport retry budget exhausted")

    @staticmethod
    def _error_class(code: int | None) -> type[TelegramApiError]:
        if code == 409:
            return TelegramConflictError
        if code is not None and 400 <= code < 500 and code != 429:
            return TelegramPermanentError
        return TelegramApiError

    def _backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        delay = self.backoff_seconds * (2**attempt)
        if response is not None and response.status_code == 429:
            try:
                retry_after = response.json().get("parameters", {}).get("retry_after", 0)
                if isinstance(retry_after, (int, float)):
                    delay = max(delay, min(float(retry_after), 30.0))
            except (ValueError, AttributeError):
                pass
        self._sleep(min(delay, 30.0))

    def _safe_description(self, value: object) -> str:
        if not isinstance(value, str):
            return ""
        return value.replace(self._token, "[redacted]")[:500]

    @classmethod
    def _parse_update(cls, value: object) -> TelegramUpdate:
        if not isinstance(value, dict) or type(value.get("update_id")) is not int:
            raise TelegramResponseError("Telegram update was malformed")
        if not 0 <= value["update_id"] < 2**63 - 1:
            raise TelegramResponseError("Telegram update was malformed")
        message_value = value.get("message")
        return TelegramUpdate(
            update_id=value["update_id"],
            message=(cls._parse_message(message_value) if message_value is not None else None),
        )

    @staticmethod
    def _parse_message(value: object) -> TelegramMessage:
        if not isinstance(value, dict):
            raise TelegramResponseError("Telegram message was malformed")
        message_id = value.get("message_id")
        chat_value = value.get("chat")
        if type(message_id) is not int or not isinstance(chat_value, dict):
            raise TelegramResponseError("Telegram message was malformed")
        chat_id = chat_value.get("id")
        chat_type = chat_value.get("type")
        if type(chat_id) is not int or not isinstance(chat_type, str):
            raise TelegramResponseError("Telegram chat was malformed")
        user_value = value.get("from")
        user = None
        if user_value is not None:
            if not isinstance(user_value, dict) or type(user_value.get("id")) is not int:
                raise TelegramResponseError("Telegram sender was malformed")
            user = TelegramUser(id=user_value["id"])
        text = value.get("text")
        if text is not None and not isinstance(text, str):
            raise TelegramResponseError("Telegram message text was malformed")
        return TelegramMessage(
            message_id=message_id,
            chat=TelegramChat(id=chat_id, type=chat_type),
            from_user=user,
            text=text,
        )


TelegramClient = TelegramBotClient
TelegramBotApiClient = TelegramBotClient
TelegramBotAPIClient = TelegramBotClient
MAX_MESSAGE_TEXT_LENGTH = MAX_TELEGRAM_TEXT_LENGTH
