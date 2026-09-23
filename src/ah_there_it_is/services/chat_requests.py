"""Local idempotency gate for chat/agent execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.agent.runner import AgentRunResult
from ah_there_it_is.agent.receipts import MutationReceipt
from ah_there_it_is.db.models import AgentRunLog, ChatRequestRecord, utc_now


class IdempotencyError(RuntimeError):
    """Base error for a reserved chat request key."""


class IdempotencyConflictError(IdempotencyError):
    """The key was reused with a different logical request."""


class IdempotencyInProgressError(IdempotencyError):
    """The original request has not reached a terminal state."""


class IdempotencyPreviousFailureError(IdempotencyError):
    """The original request already failed and is not replayed automatically."""


class ChatRequestNotFoundError(IdempotencyError):
    """A requested chat idempotency record does not exist."""


class IdempotencyRecoveryNotAllowedError(IdempotencyError):
    """An operator recovery request is invalid for the stored state."""


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
        operation: Callable[[bool], AgentRunResult],
    ) -> IdempotentExecution:
        if request_key is None:
            return IdempotentExecution(result=operation(True), replayed=False)

        key = request_key.strip()
        text = message.strip()
        record, created = self._reserve(
            request_key=key,
            message=text,
            conversation_id=conversation_id,
        )
        return self._execute_reserved(record, created, operation)

    def recover(
        self,
        *,
        source_request_key: str,
        new_request_key: str,
        recovery_note: str,
        operation: Callable[[bool], AgentRunResult],
    ) -> IdempotentExecution:
        source = self.get(source_request_key)
        if source is None:
            raise ChatRequestNotFoundError(
                f"chat request {source_request_key!r} does not exist"
            )
        if source.status == "completed":
            raise IdempotencyRecoveryNotAllowedError(
                f"completed request {source.request_key!r} must be replayed, not recovered"
            )

        note = recovery_note.strip()
        if not note:
            raise IdempotencyRecoveryNotAllowedError(
                "recovery note must describe the operator decision"
            )
        key = new_request_key.strip()
        if not key or key == source.request_key:
            raise IdempotencyRecoveryNotAllowedError(
                "recovery requires a distinct new request key"
            )

        record, created = self._reserve(
            request_key=key,
            message=source.message,
            conversation_id=source.requested_conversation_id,
            recovered_from_id=source.id,
            recovery_note=note,
        )
        return self._execute_reserved(record, created, operation)

    def recent(self, *, limit: int = 100) -> list[ChatRequestRecord]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        return list(
            self.session.scalars(
                select(ChatRequestRecord)
                .order_by(ChatRequestRecord.updated_at.desc(), ChatRequestRecord.id.desc())
                .limit(limit)
            )
        )

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
        recovered_from_id: int | None = None,
        recovery_note: str | None = None,
    ) -> tuple[ChatRequestRecord, bool]:
        existing = self.get(request_key)
        if existing is not None:
            self._assert_same_request(
                existing,
                message,
                conversation_id,
                recovered_from_id=recovered_from_id,
                recovery_note=recovery_note,
            )
            return existing, False

        record = ChatRequestRecord(
            request_key=request_key,
            requested_conversation_id=conversation_id,
            message=message,
            status="processing",
            recovered_from_id=recovered_from_id,
            recovery_note=recovery_note,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            existing = self.get(request_key)
            if existing is None:
                raise
            self._assert_same_request(
                existing,
                message,
                conversation_id,
                recovered_from_id=recovered_from_id,
                recovery_note=recovery_note,
            )
            return existing, False
        self.session.refresh(record)
        return record, True

    @staticmethod
    def _assert_same_request(
        record: ChatRequestRecord,
        message: str,
        conversation_id: int | None,
        *,
        recovered_from_id: int | None = None,
        recovery_note: str | None = None,
    ) -> None:
        if (
            record.message != message
            or record.requested_conversation_id != conversation_id
            or record.recovered_from_id != recovered_from_id
            or record.recovery_note != recovery_note
        ):
            raise IdempotencyConflictError(
                f"request key {record.request_key!r} is already bound "
                "to different chat content"
            )

    def _execute_reserved(
        self,
        record: ChatRequestRecord,
        created: bool,
        operation: Callable[[bool], AgentRunResult],
    ) -> IdempotentExecution:
        if not created:
            return IdempotentExecution(
                result=self._resolve_existing(record), replayed=True,
            )
        try:
            # The runner flushes the successful turn but leaves the final
            # transaction to this keyed-flow coordinator.
            result = operation(False)
            self._stage_completed(record.id, result.run_id)
        except Exception as exc:
            self.session.rollback()
            self._mark_failed(record.id, f"{type(exc).__name__}: {exc}")
            raise

        try:
            self._commit_completed()
        except Exception as exc:
            # A commit exception can occur after the database committed. Do
            # not infer failure from the exception or this Session's cache.
            self.session.rollback()
            return self._reconcile_commit(record.id, exc)
        return IdempotentExecution(result=result, replayed=False)

    def _stage_completed(self, record_id: int, run_id: int) -> None:
        record = self.session.get(ChatRequestRecord, record_id)
        if record is None or record.status != "processing" or record.agent_run_id is not None:
            raise IdempotencyError("reserved chat request has inconsistent processing state")
        run = self.session.get(AgentRunLog, run_id)
        if run is None or run.status != "completed":
            raise IdempotencyError("successful agent result has no completed run")
        record.agent_run_id = run_id
        record.status = "completed"
        record.error = None
        record.updated_at = utc_now()
        self.session.flush()

    def _commit_completed(self) -> None:
        self.session.commit()

    def _reconcile_commit(
        self, record_id: int, commit_error: Exception,
    ) -> IdempotentExecution:
        # A separate Session forces a durable-state read, even if the caller's
        # Session is invalidated or has stale identity-map objects.
        with Session(bind=self.session.get_bind()) as durable:
            record = durable.get(ChatRequestRecord, record_id)
            if record is None:
                raise IdempotencyError(
                    "reserved chat request disappeared during commit reconciliation"
                ) from commit_error
            if record.status == "completed":
                return IdempotentExecution(
                    result=self._result_from_record(durable, record), replayed=True,
                )
            if record.status == "processing" and record.agent_run_id is None:
                record.status = "failed"
                record.error = (
                    f"final commit failure: {type(commit_error).__name__}: {commit_error}"
                )
                record.updated_at = utc_now()
                durable.commit()
                raise commit_error
            raise IdempotencyError(
                "request has inconsistent durable state after uncertain final commit"
            ) from commit_error

    def _resolve_existing(self, record: ChatRequestRecord) -> AgentRunResult:
        if record.status == "processing":
            raise IdempotencyInProgressError(
                f"request key {record.request_key!r} is still processing"
            )
        if record.status == "failed":
            raise IdempotencyPreviousFailureError(
                f"request key {record.request_key!r} previously failed: "
                f"{record.error or 'unknown error'}"
            )
        return self._result_from_record(self.session, record)

    @staticmethod
    def _result_from_record(session: Session, record: ChatRequestRecord) -> AgentRunResult:
        if record.status != "completed" or record.agent_run_id is None:
            raise IdempotencyError(
                f"request key {record.request_key!r} has invalid stored state"
            )
        run = session.get(AgentRunLog, record.agent_run_id)
        if run is None or run.status != "completed" or run.final_content is None:
            raise IdempotencyError(
                f"request key {record.request_key!r} points to "
                "an unavailable completed run"
            )
        receipts = tuple(
            MutationReceipt.model_validate(value) for value in run.mutation_receipts
        )
        return AgentRunResult(
            conversation_id=run.conversation_id,
            run_id=run.id,
            content=run.final_content,
            rounds=run.rounds,
            changes_applied=any(receipt.changed for receipt in receipts),
            receipts=receipts,
        )

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
