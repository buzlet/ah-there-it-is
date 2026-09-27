"""Bounded Telegram typing refresh for one accepted update."""

from __future__ import annotations

from collections import deque
import random
from threading import BoundedSemaphore, Event, Thread
import time
from typing import Any, Callable


PROGRESS_DOT_INTERVAL_SECONDS = 3.5
PROGRESS_GRACE_SECONDS = 2.5
LONG_WAIT_AFTER_SECONDS = 20.0
LONG_WAIT_PHRASE_INTERVAL_SECONDS = 18.0
PROGRESS_JOIN_TIMEOUT_SECONDS = 1.5
LONG_WAIT_PHRASES = (
    "Всё ещё работаю над запросом...",
    "Запрос оказался задумчивее обычного...",
    "Не пропал — продолжаю разбираться...",
    "Инвентарь сегодня заставил задуматься...",
    "Чуть дольше обычного, но я всё ещё здесь...",
    "Разбираюсь с запросом — ничего нажимать не нужно...",
    "Задача оказалась с характером...",
    "Продолжаю, просто этот запрос не из быстрых...",
    "Всё под контролем, обработка продолжается...",
    "Ещё немного терпения — запрос всё ещё в работе...",
)
_PROGRESS_WORKER_GATE = BoundedSemaphore(1)


class TelegramDraftProgress:
    """Best-effort Bot API live draft updates for one synchronous request."""

    def __init__(
        self,
        client: Any,
        chat_id: int,
        draft_id: int,
        *,
        grace_seconds: float = PROGRESS_GRACE_SECONDS,
        interval: float = PROGRESS_DOT_INTERVAL_SECONDS,
        long_wait_after: float = LONG_WAIT_AFTER_SECONDS,
        phrase_interval: float = LONG_WAIT_PHRASE_INTERVAL_SECONDS,
        wait: Callable[[float], bool] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        stop_event: Event | None = None,
    ) -> None:
        if grace_seconds < 0 or grace_seconds > 10:
            raise ValueError("progress grace period must be between 0 and 10 seconds")
        if interval <= 0 or interval > 20:
            raise ValueError("progress interval must be between 0 and 20 seconds")
        if long_wait_after < grace_seconds or long_wait_after > 600:
            raise ValueError("long wait threshold is out of range")
        if phrase_interval < 10 or phrase_interval > 60:
            raise ValueError("long wait phrase interval must be between 10 and 60 seconds")
        if type(draft_id) is not int or not 1 <= draft_id <= 2_147_483_647:
            raise ValueError("draft_id must be a non-zero 32-bit integer")
        self.client = client
        self.chat_id = chat_id
        self.draft_id = draft_id
        self.grace_seconds = grace_seconds
        self.interval = interval
        self.long_wait_after = long_wait_after
        self.phrase_interval = phrase_interval
        self._wait_fn = wait
        self._monotonic = monotonic
        self._stop = Event()
        self._external_stop = stop_event
        self._thread: Thread | None = None
        self._draft_disabled = False
        self._phrase_random = random.Random(draft_id)
        self._phrase_pool = list(LONG_WAIT_PHRASES)
        self._phrase_random.shuffle(self._phrase_pool)
        self._phrase_queue = deque(self._phrase_pool)
        self._last_phrase: str | None = None

    def __enter__(self) -> "TelegramDraftProgress":
        if self._is_stopping() or not _PROGRESS_WORKER_GATE.acquire(blocking=False):
            return self
        self._thread = Thread(
            target=self._refresh,
            name="telegram-draft-progress",
            daemon=True,
        )
        try:
            self._thread.start()
        except Exception:
            _PROGRESS_WORKER_GATE.release()
            self._thread = None
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def stop(self) -> None:
        """Stop advisory updates before the ordinary final reply is sent."""
        if self._stop.is_set():
            return
        self._stop.set()
        if self._thread is not None:
            # Client draft/typing calls use a one-second timeout and zero
            # retries; do not let advisory progress hold up request completion.
            self._thread.join(timeout=PROGRESS_JOIN_TIMEOUT_SECONDS)

    def _refresh(self) -> None:
        try:
            started = self._monotonic()
            next_tick = started + self.grace_seconds
            dots = 0
            active_phrase: str | None = None
            next_phrase_at = started + self.long_wait_after
            neutral = (
                "Обрабатываю запрос.",
                "Обрабатываю запрос..",
                "Обрабатываю запрос...",
            )
            while not self._wait_until(next_tick):
                if self._is_stopping():
                    return
                now = self._monotonic()
                elapsed = now - started
                if elapsed >= self.long_wait_after:
                    if active_phrase is None or now >= next_phrase_at:
                        active_phrase = self._next_phrase()
                        next_phrase_at = now + self.phrase_interval
                    content = f"{active_phrase}\n{neutral[dots % len(neutral)]}"
                else:
                    content = neutral[dots % len(neutral)]
                dots += 1
                self._send(content)
                next_tick = self._monotonic() + self.interval
        finally:
            _PROGRESS_WORKER_GATE.release()

    def _wait_until(self, deadline: float) -> bool:
        while not self._is_stopping():
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return False
            if self._wait_fn is not None:
                if self._wait_fn(remaining):
                    return True
            elif self._stop.wait(min(remaining, 0.25)):
                return True
        return True

    def _send(self, content: str) -> None:
        if self._is_stopping():
            return
        if not self._draft_disabled:
            method = getattr(self.client, "send_message_draft", None)
            if callable(method):
                try:
                    method(self.chat_id, self.draft_id, content)
                    return
                except Exception:
                    # Live draft support is advisory; a failure disables further
                    # draft calls for this request. A later tick uses typing.
                    self._draft_disabled = True
                    return
            else:
                self._draft_disabled = True
        try:
            method = getattr(self.client, "send_chat_action", None)
            if callable(method):
                method(self.chat_id, "typing")
        except Exception:
            pass

    def _next_phrase(self) -> str:
        if not self._phrase_queue:
            next_pool = list(LONG_WAIT_PHRASES)
            self._phrase_random.shuffle(next_pool)
            if self._last_phrase is not None and next_pool[0] == self._last_phrase:
                next_pool[0], next_pool[1] = next_pool[1], next_pool[0]
            self._phrase_queue.extend(next_pool)
        phrase = self._phrase_queue.popleft()
        self._last_phrase = phrase
        return phrase

    def _is_stopping(self) -> bool:
        return self._stop.is_set() or (
            self._external_stop is not None and self._external_stop.is_set()
        )


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
        self._last_send_started = 0.0

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
        if self._stop.is_set() or (
            self._external_stop is not None and self._external_stop.is_set()
        ):
            return
        self._last_send_started = time.monotonic()
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

        # Include transport time in the refresh interval.
        deadline = self._last_send_started + self.interval
        while True:
            if self._stop.is_set() or (
                self._external_stop is not None and self._external_stop.is_set()
            ):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._stop.wait(min(remaining, 0.25))
