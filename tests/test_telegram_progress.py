from __future__ import annotations

from threading import Condition, Event

import pytest

from ah_there_it_is.telegram.progress import TelegramTyping


class ManualWait:
    """Advance a worker's interval without wall-clock sleeps."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._calls = 0
        self._ticks = 0
        self._closed = False

    def __call__(self, interval: float) -> bool:
        assert interval == 4.0
        with self._condition:
            self._calls += 1
            current = self._calls
            self._condition.notify_all()
            self._condition.wait_for(
                lambda: self._ticks >= current or self._closed,
                timeout=3.0,
            )
            return self._closed

    def wait_for_calls(self, count: int) -> None:
        with self._condition:
            assert self._condition.wait_for(lambda: self._calls >= count, timeout=3.0)

    def tick(self) -> None:
        with self._condition:
            self._ticks += 1
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


class ActionClient:
    def __init__(self) -> None:
        self.condition = Condition()
        self.actions: list[tuple[int, str]] = []

    def send_chat_action(self, chat_id: int, action: str) -> None:
        with self.condition:
            self.actions.append((chat_id, action))
            self.condition.notify_all()

    def wait_for_actions(self, count: int) -> None:
        with self.condition:
            assert self.condition.wait_for(lambda: len(self.actions) >= count, timeout=3.0)


def test_typing_refreshes_each_interval_and_stops_on_success() -> None:
    clock = ManualWait()
    client = ActionClient()
    try:
        with TelegramTyping(client, 71, wait=clock):
            assert client.actions == [(71, "typing")]
            clock.wait_for_calls(1)
            clock.tick()
            client.wait_for_actions(2)
            clock.wait_for_calls(2)
            clock.tick()
            client.wait_for_actions(3)
            clock.wait_for_calls(3)
            clock.close()
        assert client.actions == [(71, "typing")] * 3
    finally:
        clock.close()


@pytest.mark.parametrize("fail", [False, True])
def test_typing_thread_is_cleaned_up_after_success_or_exception(fail: bool) -> None:
    clock = ManualWait()
    client = ActionClient()
    progress = TelegramTyping(client, 71, wait=clock)
    try:
        if fail:
            with pytest.raises(RuntimeError, match="operation failed"):
                with progress:
                    clock.wait_for_calls(1)
                    clock.close()
                    raise RuntimeError("operation failed")
        else:
            with progress:
                clock.wait_for_calls(1)
                clock.close()
    finally:
        clock.close()
    assert progress._thread is not None
    assert not progress._thread.is_alive()
    assert client.actions == [(71, "typing")]


def test_external_shutdown_stops_refreshing() -> None:
    clock = ManualWait()
    client = ActionClient()
    shutdown = Event()
    progress = TelegramTyping(client, 71, wait=clock, stop_event=shutdown)
    try:
        with progress:
            clock.wait_for_calls(1)
            clock.tick()
            client.wait_for_actions(2)
            clock.wait_for_calls(2)
            shutdown.set()
            clock.tick()
            # The external stop is checked after each deterministic interval.
            assert progress._thread is not None
            progress._thread.join(timeout=3.0)
            assert not progress._thread.is_alive()
        assert client.actions == [(71, "typing")] * 2
    finally:
        clock.close()
