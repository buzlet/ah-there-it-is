"""Restart-safe Telegram update processing state machine."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any

from ah_there_it_is.telegram.adapter import TelegramAdapter, TelegramAdapterResult


@dataclass(frozen=True)
class TelegramPollResult:
    fetched: int
    processed: int
    discarded: int
    next_offset: int
    outcomes: tuple[TelegramAdapterResult, ...] = ()


class TelegramPollingService:
    """Process updates in ID order and checkpoint only after safe handling."""

    def __init__(
        self,
        adapter: TelegramAdapter,
        client: Any | None = None,
        *,
        poll_timeout: int = 30,
        limit: int = 100,
    ) -> None:
        if poll_timeout < 0 or poll_timeout > 50:
            raise ValueError("poll_timeout must be between 0 and 50")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        self.adapter = adapter
        self.client = client or adapter.client
        self.poll_timeout = poll_timeout
        self.limit = limit

    def run_once(self) -> TelegramPollResult:
        offset = self.adapter.next_offset()
        updates = list(
            self.client.get_updates(
                offset=offset,
                timeout=self.poll_timeout,
                limit=self.limit,
            )
        )
        ordered = sorted(updates, key=lambda update: update.update_id)
        outcomes: list[TelegramAdapterResult] = []
        processed = 0
        discarded = 0
        for update in ordered:
            if update.update_id < offset:
                continue
            request_key = f"telegram:{update.update_id}"
            if not self.adapter.accepts(update):
                outcome = self.adapter.process_update(
                    update, request_key=request_key, send_reply=False
                )
                self.adapter.acknowledge_update(update.update_id)
                outcomes.append(outcome)
                discarded += 1
                continue

            outcome = self.adapter.process_update(
                update,
                request_key=request_key,
                send_reply=True,
            )
            # A successful send is the point at which this update can be acked.
            self.adapter.acknowledge_update(update.update_id)
            outcomes.append(outcome)
            processed += 1
        return TelegramPollResult(
            fetched=len(updates),
            processed=processed,
            discarded=discarded,
            next_offset=self.adapter.next_offset(),
            outcomes=tuple(outcomes),
        )

    def run_forever(self, *, stop_event: Event | None = None) -> None:
        stop = stop_event or Event()
        while not stop.is_set():
            self.run_once()

    poll_once = run_once
    process_updates = run_once


TelegramPollingLoop = TelegramPollingService
TelegramUpdateProcessor = TelegramPollingService
