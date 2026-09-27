from __future__ import annotations

from threading import Condition, Event

import pytest

from ah_there_it_is.telegram.progress import LONG_WAIT_PHRASES, TelegramDraftProgress, TelegramTyping


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


class ManualClock:
    """Let a progress worker advance virtual monotonic time at each wait."""

    def __init__(self) -> None:
        self.condition = Condition()
        self.now = 0.0
        self.calls = 0
        self.ticks = 0
        self.waits: list[float] = []
        self.closed = False

    def monotonic(self) -> float:
        with self.condition:
            return self.now

    def __call__(self, seconds: float) -> bool:
        with self.condition:
            self.calls += 1
            current = self.calls
            self.waits.append(seconds)
            self.condition.notify_all()
            self.condition.wait_for(
                lambda: self.ticks >= current or self.closed,
                timeout=2.0,
            )
            return self.closed

    def wait_for_calls(self, count: int) -> None:
        with self.condition:
            assert self.condition.wait_for(lambda: self.calls >= count, timeout=2.0)

    def tick(self) -> None:
        with self.condition:
            self.now += self.waits[self.ticks]
            self.ticks += 1
            self.condition.notify_all()

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class DraftClient:
    def __init__(self, *, fail_draft: bool = False) -> None:
        self.condition = Condition()
        self.drafts: list[tuple[int, int, str]] = []
        self.actions: list[tuple[int, str]] = []
        self.fail_draft = fail_draft

    def send_message_draft(self, chat_id: int, draft_id: int, text: str) -> None:
        if self.fail_draft:
            raise RuntimeError("advisory transport failed")
        with self.condition:
            self.drafts.append((chat_id, draft_id, text))
            self.condition.notify_all()

    def send_chat_action(self, chat_id: int, action: str) -> None:
        with self.condition:
            self.actions.append((chat_id, action))
            self.condition.notify_all()

    def wait_for_drafts(self, count: int) -> None:
        with self.condition:
            assert self.condition.wait_for(lambda: len(self.drafts) >= count, timeout=2.0)


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


def test_already_requested_shutdown_does_not_send_initial_action() -> None:
    client = ActionClient()
    shutdown = Event()
    shutdown.set()
    with TelegramTyping(client, 71, stop_event=shutdown):
        pass
    assert client.actions == []


def test_refresh_interval_includes_transport_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from ah_there_it_is.telegram import progress as progress_module

    now = [0.0]
    waits = []
    monkeypatch.setattr(progress_module.time, "monotonic", lambda: now[0])

    class SlowClient:
        def send_chat_action(self, chat_id, action):
            now[0] += 1.0

    progress = TelegramTyping(SlowClient(), 71)

    def advance(seconds):
        waits.append(seconds)
        now[0] += seconds
        return False

    monkeypatch.setattr(progress._stop, "wait", advance)
    progress._send()
    assert progress._wait_interval() is False
    assert sum(waits) == 3.0
    assert now[0] == 4.0


def test_live_draft_grace_period_and_dot_animation_use_one_stable_id() -> None:
    clock = ManualClock()
    client = DraftClient()
    progress = TelegramDraftProgress(
        client,
        71,
        123,
        grace_seconds=2.5,
        interval=3.5,
        wait=clock,
        monotonic=clock.monotonic,
    )
    try:
        with progress:
            clock.wait_for_calls(1)
            assert client.drafts == []
            clock.tick()
            client.wait_for_drafts(1)
            for count in (2, 3):
                clock.wait_for_calls(count)
                clock.tick()
                client.wait_for_drafts(count)
            clock.close()
    finally:
        clock.close()
    assert [draft[0:2] for draft in client.drafts] == [(71, 123)] * 3
    assert [draft[2] for draft in client.drafts] == [
        "Обрабатываю запрос.",
        "Обрабатываю запрос..",
        "Обрабатываю запрос...",
    ]
    assert all("секунд" not in draft[2] for draft in client.drafts)
    assert progress._thread is not None and not progress._thread.is_alive()


def test_long_wait_phrase_pool_exhausts_all_ten_before_reshuffle() -> None:
    progress = TelegramDraftProgress(DraftClient(), 71, 124)

    first_cycle = [progress._next_phrase() for _ in range(10)]
    second_cycle = [progress._next_phrase() for _ in range(10)]

    assert len(set(first_cycle)) == 10
    assert set(first_cycle) == set(LONG_WAIT_PHRASES)
    assert len(set(second_cycle)) == 10
    assert set(second_cycle) == set(LONG_WAIT_PHRASES)
    assert second_cycle[0] != first_cycle[-1]


def test_long_wait_phrase_rotates_slowly_while_dots_continue() -> None:
    clock = ManualClock()
    client = DraftClient()
    progress = TelegramDraftProgress(
        client,
        71,
        127,
        wait=clock,
        monotonic=clock.monotonic,
    )
    try:
        with progress:
            for count in range(1, 7):
                clock.wait_for_calls(count)
                clock.tick()
                client.wait_for_drafts(count)
            first_phrase = progress._last_phrase
            assert first_phrase in LONG_WAIT_PHRASES
            assert "\nОбрабатываю запрос." in client.drafts[-1][2]
            first_phrase_index = next(
                index for index, draft in enumerate(client.drafts) if first_phrase in draft[2]
            )
            for count in range(7, 13):
                clock.wait_for_calls(count)
                clock.tick()
                client.wait_for_drafts(count)
            clock.close()
        long_wait_texts = [draft[2] for draft in client.drafts[first_phrase_index:]]
        assert all(first_phrase in text for text in long_wait_texts[:5])
        assert progress._last_phrase != first_phrase
        assert progress._thread is not None and not progress._thread.is_alive()
    finally:
        clock.close()


def test_progress_transport_failure_is_advisory_and_typing_is_only_fallback() -> None:
    client = DraftClient(fail_draft=True)
    progress = TelegramDraftProgress(client, 71, 125)

    progress._send("Обрабатываю запрос.")

    assert progress._draft_disabled is True
    assert client.actions == []
    progress._send("Обрабатываю запрос..")
    assert client.actions == [(71, "typing")]


def test_progress_worker_stops_after_request_failure_and_shutdown() -> None:
    clock = ManualClock()
    client = DraftClient()
    shutdown = Event()
    progress = TelegramDraftProgress(
        client,
        71,
        126,
        wait=clock,
        monotonic=clock.monotonic,
        stop_event=shutdown,
    )
    try:
        with pytest.raises(RuntimeError, match="operation failed"):
            with progress:
                clock.wait_for_calls(1)
                clock.tick()
                client.wait_for_drafts(1)
                shutdown.set()
                clock.close()
                raise RuntimeError("operation failed")
    finally:
        clock.close()
    assert progress._thread is not None and not progress._thread.is_alive()
    assert len(client.drafts) == 1


def test_blocked_advisory_worker_does_not_spawn_more_workers_or_block_shutdown(monkeypatch) -> None:
    from ah_there_it_is.telegram import progress as module

    entered = Event()
    release = Event()
    class BlockedClient:
        def send_message_draft(self, *args):
            entered.set()
            assert release.wait(timeout=2)
    monkeypatch.setattr(module, "PROGRESS_JOIN_TIMEOUT_SECONDS", 0)
    progress = TelegramDraftProgress(BlockedClient(), 71, 321, grace_seconds=0)
    try:
        with progress:
            assert entered.wait(timeout=2)
        assert progress._stop.is_set()
        for draft_id in range(322, 332):
            with TelegramDraftProgress(DraftClient(), 71, draft_id) as other:
                assert other._thread is None
    finally:
        release.set()
        progress._thread.join(timeout=2)
    assert not progress._thread.is_alive()
    with TelegramDraftProgress(DraftClient(), 71, 333) as recovered:
        assert recovered._thread is not None
