"""Small, token-safe httpx transport for the Telegram Bot API."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import secrets
import time
from typing import Any

import httpx


DEFAULT_TELEGRAM_BASE_URL = "https://api.telegram.org"
MAX_TELEGRAM_TEXT_LENGTH = 4096
ADVISORY_TIMEOUT_SECONDS = 1.0
MAX_CALLBACK_QUERY_ID_LENGTH = 256


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
    is_bot: bool = False


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
    callback_query: TelegramCallbackQuery | None = None


@dataclass(frozen=True)
class TelegramCallbackQuery:
    id: str
    from_user: TelegramUser
    message: TelegramMessage | None
    data: str | None
    inline_message_id: str | None = None


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
        payload: dict[str, Any] = {
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)
        if not isinstance(result, list):
            raise TelegramResponseError("Telegram getUpdates result was malformed")
        return [self._parse_update(value) for value in result]

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: Mapping[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> tuple[TelegramMessage, ...]:
        """Send plain text, splitting deterministically at the isolated limit."""
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            raise ValueError("chat_id must be an integer")
        if not isinstance(text, str) or not text:
            raise ValueError("text must not be empty")
        if parse_mode not in {None, "HTML"}:
            raise ValueError("unsupported Telegram parse mode")
        chunks = tuple(
            text[index : index + MAX_TELEGRAM_TEXT_LENGTH]
            for index in range(0, len(text), MAX_TELEGRAM_TEXT_LENGTH)
        )
        messages: list[TelegramMessage] = []
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if parse_mode is not None:
                payload["parse_mode"] = parse_mode
            if reply_markup is not None and index == len(chunks) - 1:
                payload["reply_markup"] = dict(reply_markup)
            result = self._call(
                "sendMessage",
                payload,
            )
            messages.append(self._parse_message(result))
        return tuple(messages)

    def send_message_draft(self, chat_id: int, draft_id: int, text: str) -> None:
        """Send one bounded, ephemeral Bot API draft update."""
        self._validate_chat_id(chat_id)
        if type(draft_id) is not int or not 1 <= draft_id <= 2_147_483_647:
            raise ValueError("draft_id must be a non-zero 32-bit integer")
        if not isinstance(text, str) or not text or len(text) > MAX_TELEGRAM_TEXT_LENGTH:
            raise ValueError("draft text has an invalid length")
        try:
            result = self._call(
                "sendMessageDraft",
                {"chat_id": chat_id, "draft_id": draft_id, "text": text},
                timeout=httpx.Timeout(ADVISORY_TIMEOUT_SECONDS),
                max_retries=0,
            )
        except TelegramClientError:
            raise TelegramClientError("Telegram draft request failed") from None
        if result is not True:
            raise TelegramResponseError("Telegram draft result was malformed")

    def answer_callback_query(self, callback_query_id: str) -> None:
        if (
            not isinstance(callback_query_id, str)
            or not callback_query_id
            or len(callback_query_id) > MAX_CALLBACK_QUERY_ID_LENGTH
        ):
            raise ValueError("callback query id is malformed")
        try:
            result = self._call(
                "answerCallbackQuery",
                {"callback_query_id": callback_query_id},
                timeout=httpx.Timeout(ADVISORY_TIMEOUT_SECONDS),
                max_retries=0,
            )
        except TelegramClientError:
            raise TelegramClientError("Telegram callback answer failed") from None
        if result is not True:
            raise TelegramResponseError("Telegram callback answer result was malformed")

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        reply_markup: Mapping[str, Any] | None = None,
        parse_mode: str | None = None,
    ) -> None:
        self._validate_chat_id(chat_id)
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("message_id must be positive")
        if not isinstance(text, str) or not text or len(text) > MAX_TELEGRAM_TEXT_LENGTH:
            raise ValueError("edited text has an invalid length")
        if parse_mode not in {None, "HTML"}:
            raise ValueError("unsupported Telegram parse mode")
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode is not None:
            payload["parse_mode"] = parse_mode
        if reply_markup is not None:
            payload["reply_markup"] = dict(reply_markup)
        try:
            result = self._call(
                "editMessageText",
                payload,
                timeout=httpx.Timeout(ADVISORY_TIMEOUT_SECONDS),
                max_retries=0,
            )
        except TelegramClientError:
            raise TelegramClientError("Telegram message edit failed") from None
        if result is not True and not isinstance(result, dict):
            raise TelegramResponseError("Telegram message edit result was malformed")

    @staticmethod
    def new_draft_id() -> int:
        """Return a non-zero API-safe ID, generated once for one in-flight request."""
        return secrets.randbelow(2_147_483_647) + 1

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self._validate_chat_id(chat_id)
        if action != "typing":
            raise ValueError("unsupported chat action")
        try:
            result = self._call(
                "sendChatAction", {"chat_id": chat_id, "action": action},
                timeout=httpx.Timeout(ADVISORY_TIMEOUT_SECONDS),
                max_retries=0,
            )
        except TelegramClientError:
            # Telegram may echo request identity in API descriptions.
            raise TelegramClientError("Telegram chat action request failed") from None
        if result is not True:
            raise TelegramResponseError("Telegram sendChatAction result was malformed")

    send_text = send_message

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TelegramBotClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _call(
        self, method: str, payload: Mapping[str, Any], *,
        timeout: httpx.Timeout | None = None, max_retries: int | None = None,
    ) -> Any:
        url = f"{self.base_url}/bot{self._token}/{method}"
        retries = self.max_retries if max_retries is None else max_retries
        for attempt in range(retries + 1):
            try:
                response = self._client.post(url, json=dict(payload), timeout=timeout or self.timeout)
            except httpx.RequestError as exc:
                if attempt >= retries:
                    raise TelegramTransportError(
                        f"Telegram transport failed ({type(exc).__name__})"
                    ) from None
                self._backoff(attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries:
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
                description = self._safe_description(body.get("description"), payload)
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

    def _safe_description(
        self, value: object, payload: Mapping[str, Any] | None = None
    ) -> str:
        if not isinstance(value, str):
            return ""
        safe = value.replace(self._token, "[redacted]")
        for key in (
            "chat_id",
            "message_id",
            "callback_query_id",
            "user_id",
        ):
            identity = payload.get(key) if payload is not None else None
            if isinstance(identity, (str, int)) and not isinstance(identity, bool):
                safe = safe.replace(str(identity), "[redacted]")
        return safe[:500]

    @staticmethod
    def _validate_chat_id(chat_id: int) -> None:
        if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id == 0:
            raise ValueError("chat_id must be a non-zero integer")

    @classmethod
    def _parse_update(cls, value: object) -> TelegramUpdate:
        if not isinstance(value, dict) or type(value.get("update_id")) is not int:
            raise TelegramResponseError("Telegram update was malformed")
        if not 0 <= value["update_id"] < 2**63 - 1:
            raise TelegramResponseError("Telegram update was malformed")
        message_value = value.get("message")
        callback_value = value.get("callback_query")
        return TelegramUpdate(
            update_id=value["update_id"],
            message=(cls._parse_message(message_value) if message_value is not None else None),
            callback_query=(
                cls._parse_callback_query(callback_value)
                if callback_value is not None
                else None
            ),
        )

    @classmethod
    def _parse_callback_query(cls, value: object) -> TelegramCallbackQuery:
        if not isinstance(value, dict):
            raise TelegramResponseError("Telegram callback query was malformed")
        query_id = value.get("id")
        user_value = value.get("from")
        if (
            not isinstance(query_id, str)
            or not query_id
            or len(query_id) > MAX_CALLBACK_QUERY_ID_LENGTH
            or not isinstance(user_value, dict)
        ):
            raise TelegramResponseError("Telegram callback query was malformed")
        user = cls._parse_user(user_value)
        message_value = value.get("message")
        inline_message_id = value.get("inline_message_id")
        data = value.get("data")
        if inline_message_id is not None and not isinstance(inline_message_id, str):
            raise TelegramResponseError("Telegram callback message was malformed")
        if data is not None and not isinstance(data, str):
            raise TelegramResponseError("Telegram callback data was malformed")
        return TelegramCallbackQuery(
            id=query_id,
            from_user=user,
            message=cls._parse_message(message_value) if message_value is not None else None,
            data=data,
            inline_message_id=inline_message_id,
        )

    @classmethod
    def _parse_message(cls, value: object) -> TelegramMessage:
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
        user = cls._parse_user(user_value) if user_value is not None else None
        text = value.get("text")
        if text is not None and not isinstance(text, str):
            raise TelegramResponseError("Telegram message text was malformed")
        return TelegramMessage(
            message_id=message_id,
            chat=TelegramChat(id=chat_id, type=chat_type),
            from_user=user,
            text=text,
        )

    @staticmethod
    def _parse_user(value: object) -> TelegramUser:
        if not isinstance(value, dict) or type(value.get("id")) is not int:
            raise TelegramResponseError("Telegram sender was malformed")
        is_bot = value.get("is_bot", False)
        if type(is_bot) is not bool:
            raise TelegramResponseError("Telegram sender was malformed")
        return TelegramUser(id=value["id"], is_bot=is_bot)


TelegramClient = TelegramBotClient
TelegramBotApiClient = TelegramBotClient
TelegramBotAPIClient = TelegramBotClient
MAX_MESSAGE_TEXT_LENGTH = MAX_TELEGRAM_TEXT_LENGTH
