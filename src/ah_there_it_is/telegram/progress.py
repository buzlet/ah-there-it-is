"""Bounded Telegram typing refresh for one accepted update."""

from __future__ import annotations

from threading import Event, Thread
import time
from typing import Any, Callable


class TelegramTyping:
    def __init__(
        self,
        client: Any,
        chat_id: int,
        *,
        interval: float = 4.0,
        wait: Callable[[float], bool] | None = None,
        stop_event: Event | None = None,
    ) -> None:
        if interval <= 0 or interval > 20:
            raise ValueError("typing interval must be between 0 and 20 seconds")
        self.client = client
        self.chat_id = chat_id
        self.interval = interval
        self._stop = Event()
        self._wait_fn = wait
        self._external_stop = stop_event
        self._thread: Thread | None = None

    def __enter__(self) -> "TelegramTyping":
        self._send()
        self._thread = Thread(
            target=self._refresh,
            name="telegram-typing",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _send(self) -> None:
        try:
            method = getattr(self.client, "send_chat_action", None)
            if callable(method):
                method(self.chat_id, "typing")
        except Exception:
            # Progress is advisory and cannot affect request execution.
            pass

    def _refresh(self) -> None:
        while not self._wait_interval():
            if self._stop.is_set() or (
                self._external_stop is not None and self._external_stop.is_set()
            ):
                return
            self._send()

    def _wait_interval(self) -> bool:
        if self._stop.is_set() or (
            self._external_stop is not None and self._external_stop.is_set()
        ):
            return True
        if self._wait_fn is not None:
            return self._wait_fn(self.interval)

        deadline = time.monotonic() + self.interval
        while True:
            if self._stop.is_set() or (
                self._external_stop is not None and self._external_stop.is_set()
            ):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._stop.wait(min(remaining, 0.25))
