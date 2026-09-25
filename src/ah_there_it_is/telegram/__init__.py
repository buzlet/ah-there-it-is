"""Narrow Telegram Bot API transport and adapter-facing value objects."""

from .client import (
    DEFAULT_TELEGRAM_BASE_URL,
    MAX_MESSAGE_TEXT_LENGTH,
    MAX_TELEGRAM_TEXT_LENGTH,
    TelegramApiError,
    TelegramBotClient,
    TelegramBotAPIClient,
    TelegramBotApiClient,
    TelegramClient,
    TelegramClientError,
    TelegramChat,
    TelegramMessage,
    TelegramResponseError,
    TelegramTransportError,
    TelegramUpdate,
    TelegramUser,
)

__all__ = [
    "DEFAULT_TELEGRAM_BASE_URL",
    "MAX_MESSAGE_TEXT_LENGTH",
    "MAX_TELEGRAM_TEXT_LENGTH",
    "TelegramApiError",
    "TelegramBotClient",
    "TelegramBotAPIClient",
    "TelegramBotApiClient",
    "TelegramClient",
    "TelegramClientError",
    "TelegramChat",
    "TelegramMessage",
    "TelegramResponseError",
    "TelegramTransportError",
    "TelegramUpdate",
    "TelegramUser",
]
