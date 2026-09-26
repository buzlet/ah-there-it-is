"""Explicit Telegram bot runtime construction and bounded polling loop."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import time
from threading import Event
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.agent.runner import SYSTEM_PROMPT
from ah_there_it_is.config import Settings, get_settings
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.chat_application import ChatApplicationService
from ah_there_it_is.telegram.adapter import TelegramAdapter
from ah_there_it_is.telegram.client import (
    TelegramBotClient, TelegramClientError, TelegramConflictError,
    TelegramPermanentError,
)
from ah_there_it_is.telegram.polling import TelegramPollingService


class TelegramRuntimeConfigurationError(ValueError):
    """Required Telegram runtime settings are absent or invalid."""


def validate_telegram_settings(settings: Settings) -> None:
    """Validate bot-only settings without ever including the token in errors."""
    if settings.telegram_bot_token is None or not settings.telegram_bot_token.strip():
        raise TelegramRuntimeConfigurationError(
            "Telegram bot token is required for 'ah-there-it-is telegram-bot'"
        )
    user_id = settings.telegram_allowed_user_id
    if type(user_id) is not int or user_id <= 0:
        raise TelegramRuntimeConfigurationError(
            "Telegram allowed user id is required for 'ah-there-it-is telegram-bot'"
        )
    label = settings.telegram_source_label
    if label is not None and settings.telegram_bot_token.strip() in label:
        raise TelegramRuntimeConfigurationError(
            "Telegram source label must not contain the bot token"
        )


def _load_system_prompt(settings: Settings) -> str:
    if settings.prompt_file is None:
        return SYSTEM_PROMPT
    return Path(settings.prompt_file).read_text(encoding="utf-8")


@dataclass
class TelegramRuntime(AbstractContextManager["TelegramRuntime"]):
    """Own one database session, adapter and explicit polling process."""

    settings: Settings
    session: Session
    client: Any
    polling: TelegramPollingService
    engine: Engine | None = None
    sleep: Callable[[float], None] = time.sleep
    _closed: bool = False

    def __enter__(self) -> "TelegramRuntime":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close_client = getattr(self.client, "close", None)
        if callable(close_client):
            close_client()
        self.session.close()
        if self.engine is not None:
            self.engine.dispose()

    def run_forever(self, *, stop_event: Event | None = None) -> None:
        """Poll until stopped, retrying transient Telegram failures."""
        stop = stop_event or Event()
        failures = 0
        conflicts = 0
        ready = False
        while not stop.is_set():
            try:
                self.polling.run_once()
            except TelegramConflictError:
                conflicts += 1
                if conflicts >= 3:
                    raise TelegramPermanentError(
                        "Telegram polling conflict persisted (status=409)",
                        status_code=409,
                    ) from None
                self.sleep(
                    min(30.0, self.settings.telegram_retry_backoff_seconds * conflicts)
                )
            except TelegramPermanentError:
                raise
            except TelegramClientError:
                conflicts = 0
                delay = min(
                    30.0,
                    self.settings.telegram_retry_backoff_seconds
                    * (2 ** min(failures, 8)),
                )
                failures += 1
                if delay > 0:
                    self.sleep(delay)
            else:
                failures = 0
                conflicts = 0
                if not ready:
                    _notify_systemd_ready()
                    ready = True


def _notify_systemd_ready() -> None:
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(b"READY=1", address)
    except OSError:
        raise TelegramRuntimeConfigurationError(
            "Telegram systemd readiness notification failed"
        ) from None


def build_telegram_runtime(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    llm_factory: Callable[[], Any] | None = None,
    telegram_client: Any | None = None,
    poll_timeout: int = 30,
    limit: int = 100,
    sleep: Callable[[float], None] = time.sleep,
) -> TelegramRuntime:
    """Construct the bot process without running a poll loop."""
    validate_telegram_settings(settings)

    engine: Engine | None = None
    if session_factory is None:
        engine = create_db_engine(settings.database_url)
        session_factory = create_session_factory(engine)
    session = session_factory()
    client = telegram_client
    try:
        if client is None:
            client = TelegramBotClient(
                settings.telegram_bot_token or "",
                base_url=settings.telegram_base_url,
                timeout_seconds=settings.telegram_timeout_seconds,
                max_retries=settings.telegram_max_retries,
                backoff_seconds=settings.telegram_retry_backoff_seconds,
            )
        application = ChatApplicationService(
            session,
            llm_factory or build_llm_factory(settings),
            max_rounds=settings.agent_max_rounds,
            system_prompt=_load_system_prompt(settings),
            prompt_version=settings.prompt_version,
        )
        adapter = TelegramAdapter(
            session,
            application,
            client,
            allowed_user_id=settings.telegram_allowed_user_id,  # type: ignore[arg-type]
            source_label=settings.telegram_source_label,
        )
        polling = TelegramPollingService(
            adapter,
            client,
            poll_timeout=poll_timeout,
            limit=limit,
        )
        return TelegramRuntime(
            settings=settings,
            session=session,
            client=client,
            polling=polling,
            engine=engine,
            sleep=sleep,
        )
    except Exception:
        close_client = getattr(client, "close", None)
        if callable(close_client):
            close_client()
        session.close()
        if engine is not None:
            engine.dispose()
        raise


def run_telegram_bot(
    settings: Settings | None = None,
    *,
    stop_event: Event | None = None,
    session_factory: sessionmaker[Session] | Callable[[], Session] | None = None,
    llm_factory: Callable[[], Any] | None = None,
    telegram_client: Any | None = None,
    poll_timeout: int = 30,
    limit: int = 100,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one explicit bot process and shut down cleanly on interruption."""
    selected = settings or get_settings()
    try:
        with build_telegram_runtime(
            selected,
            session_factory=session_factory,
            llm_factory=llm_factory,
            telegram_client=telegram_client,
            poll_timeout=poll_timeout,
            limit=limit,
            sleep=sleep,
        ) as runtime:
            try:
                runtime.run_forever(stop_event=stop_event)
            except KeyboardInterrupt:
                return 0
    except KeyboardInterrupt:
        return 0
    return 0


__all__ = [
    "TelegramRuntime",
    "TelegramRuntimeConfigurationError",
    "build_telegram_runtime",
    "run_telegram_bot",
    "validate_telegram_settings",
]
