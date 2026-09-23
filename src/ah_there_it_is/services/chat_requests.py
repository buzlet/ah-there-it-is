"""Local idempotency gate for chat/agent execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.agent.runner import AgentRunResult
from ah_there_it_is.db.models import AgentRunLog, ChatRequestRecord, utc_now


class IdempotencyError(RuntimeError):
    """Base error for a reserved chat request key."""


class IdempotencyConflictError(IdempotencyError):
    """The key was reused with a different logical request."""


class IdempotencyInProgressError(IdempotencyError):
    """The original request has not reached a terminal state."""


class IdempotencyPreviousFailureError(IdempotencyError):
    """The original request already failed and is not replayed automatically."""


@dataclass(frozen=True)
class IdempotentExecution:
    result: AgentRunResult
    replayed: bool


class ChatRequestService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def execute(
        self,
        *,
        request_key: str | None,
        message: str,
        conversation_id: int | None,
        operation: Callable[[], AgentRunResult],
    ) -> IdempotentExecution:
        if request_key is None:
            return IdempotentExecution(result=operation(), replayed=False)

        key = request_key.strip()
        text = message.strip()
        record, created = self._reserve(
            request_key=key,
            message=text,
            conversation_id=conversation_id,
        )
        if not created:
            return IdempotentExecution(
                result=self._resolve_existing(record),
                replayed=True,
            )

        try:
            result = operation()
        except Exception as exc:
            self.session.rollback()
            self._mark_failed(record.id, f"{type(exc).__name__}: {exc}")
            raise

        self._mark_completed(record.id, result.run_id)
        return IdempotentExecution(result=result, replayed=False)

    def get(self, request_key: str) -> ChatRequestRecord | None:
        return self.session.scalar(
            select(ChatRequestRecord).where(
                ChatRequestRecord.request_key == request_key
            )
        )

    def _reserve(
        self,
        *,
        request_key: str,
        message: str,
        conversation_id: int | None,
    ) -> tuple[ChatRequestRecord, bool]:
        existing = self.get(request_key)
        if existing is not None:
            self._assert_same_request(existing, message, conversation_id)
            return existing, False

        record = ChatRequestRecord(
            request_key=request_key,
            requested_conversation_id=conversation_id,
            message=message,
            status="processing",
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get(request_key)
            if existing is None:
                raise
            self._assert_same_request(existing, message, conversation_id)
            return existing, False
        self.session.refresh(record)
        return record, True

    @staticmethod
    def _assert_same_request(
        record: ChatRequestRecord,
        message: str,
        conversation_id: int | None,
    ) -> None:
        if (
            record.message != message
            or record.requested_conversation_id != conversation_id
        ):
            raise IdempotencyConflictError(
                f"request key {record.request_key!r} is already bound "
                "to different chat content"
            )

    def _resolve_existing(
        self,
        record: ChatRequestRecord,
    ) -> AgentRunResult:
        if record.status == "processing":
            raise IdempotencyInProgressError(
                f"request key {record.request_key!r} is still processing"
            )
        if record.status == "failed":
            raise IdempotencyPreviousFailureError(
                f"request key {record.request_key!r} previously failed: "
                f"{record.error or 'unknown error'}"
            )
        if record.status != "completed" or record.agent_run_id is None:
            raise IdempotencyError(
                f"request key {record.request_key!r} has invalid stored state"
            )

        run = self.session.get(AgentRunLog, record.agent_run_id)
        if (
            run is None
            or run.status != "completed"
            or run.final_content is None
        ):
            raise IdempotencyError(
                f"request key {record.request_key!r} points to "
                "an unavailable completed run"
            )
        return AgentRunResult(
            conversation_id=run.conversation_id,
            run_id=run.id,
            content=run.final_content,
            rounds=run.rounds,
        )

    def _mark_completed(self, record_id: int, run_id: int) -> None:
        record = self.session.get(ChatRequestRecord, record_id)
        if record is None:
            raise IdempotencyError("reserved chat request disappeared")
        record.agent_run_id = run_id
        record.status = "completed"
        record.error = None
        record.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(record)

    def _mark_failed(self, record_id: int, error: str) -> None:
        # AgentRunner may have rolled back its own business transaction, so
        # reload the reservation after that rollback before marking it terminal.
        record = self.session.get(ChatRequestRecord, record_id)
        if record is None:
            raise IdempotencyError("reserved chat request disappeared")
        record.status = "failed"
        record.error = error
        record.updated_at = utc_now()
        self.session.commit()
