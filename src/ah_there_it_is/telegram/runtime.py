"""Explicit Telegram bot runtime construction and bounded polling loop."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
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
from ah_there_it_is.telegram.client import TelegramBotClient, TelegramClientError
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
    if user_id is None or isinstance(user_id, bool):
        raise TelegramRuntimeConfigurationError(
            "Telegram allowed user id is required for 'ah-there-it-is telegram-bot'"
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
        """Poll until stopped, retrying only bounded Telegram transport errors."""
        stop = stop_event or Event()
        failures = 0
        while not stop.is_set():
            try:
                self.polling.run_once()
            except TelegramClientError:
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
