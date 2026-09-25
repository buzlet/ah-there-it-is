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
from .adapter import TelegramAdapter, TelegramAdapterResult, SingleUserTelegramAdapter
from .polling import (
    TelegramPollResult,
    TelegramPollingLoop,
    TelegramPollingService,
    TelegramUpdateProcessor,
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
    "TelegramAdapter",
    "TelegramAdapterResult",
    "SingleUserTelegramAdapter",
    "TelegramPollResult",
    "TelegramPollingLoop",
    "TelegramPollingService",
    "TelegramUpdateProcessor",
]
