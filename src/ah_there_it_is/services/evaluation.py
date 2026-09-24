"""Agent run logging and user feedback for prompt/model evaluation."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import AgentFeedback, AgentRunLog, utc_now
from ah_there_it_is.domain.exceptions import EntityNotFoundError


@dataclass(frozen=True)
class EvaluationSummary:
    prompt_version: str
    prompt_hash: str
    llm_provider: str
    llm_model: str
    llm_config_hash: str
    llm_config: dict[str, Any]
    runs: int
    rated_runs: int
    average_rating: float | None


@dataclass(frozen=True)
class EvaluationRunPage:
    runs: list[AgentRunLog]
    page: int
    page_size: int
    total: int
    has_previous: bool
    has_next: bool


@dataclass(frozen=True)
class EvaluationExportRecord:
    run_id: int
    conversation_id: int
    prompt_version: str
    prompt_hash: str
    system_prompt: str
    llm_provider: str
    llm_model: str
    llm_config: dict[str, Any]
    input_messages: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    final_content: str | None
    rounds: int
    status: str
    error: str | None
    rating: int
    comment: str | None
    created_at: datetime


def canonical_llm_config(config: dict[str, Any]) -> tuple[str, str]:
    canonical = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return canonical, digest


class EvaluationService:
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100
    EXPORT_CHUNK_SIZE = 500

    def __init__(self, session: Session) -> None:
        self.session = session

    def record_run(
        self,
        *,
        conversation_id: int,
        user_message_id: int | None,
        assistant_message_id: int | None,
        prompt_version: str,
        prompt_hash: str,
        system_prompt: str,
        llm_provider: str,
        llm_model: str,
        llm_config: dict[str, Any],
        input_messages: Sequence[dict[str, Any]],
        tool_trace: Sequence[dict[str, Any]],
        mutation_receipts: Sequence[dict[str, Any]] = (),
        final_content: str | None,
        rounds: int,
        status: str,
        error: str | None = None,
        commit: bool = True,
    ) -> AgentRunLog:
        run = AgentRunLog(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            system_prompt=system_prompt,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_config=dict(llm_config),
            input_messages=list(input_messages),
            tool_trace=list(tool_trace),
            mutation_receipts=list(mutation_receipts),
            final_content=final_content,
            rounds=rounds,
            status=status,
            error=error,
        )
        self.session.add(run)
        self._persist(run, commit=commit)
        return run

    def get_run(self, run_id: int) -> AgentRunLog:
        stmt = (
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .where(AgentRunLog.id == run_id)
        )
        run = self.session.scalar(stmt)
        if run is None:
            raise EntityNotFoundError(f"agent run id={run_id} does not exist")
        return run

    def set_feedback(
        self, run_id: int, *, rating: int, comment: str | None = None
    ) -> AgentFeedback:
        if not 1 <= rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        run = self.get_run(run_id)
        feedback = run.feedback
        if feedback is None:
            feedback = AgentFeedback(run=run, rating=rating, comment=self._clean_comment(comment))
            self.session.add(feedback)
        else:
            feedback.rating = rating
            feedback.comment = self._clean_comment(comment)
            feedback.updated_at = utc_now()
        self._commit(feedback)
        return feedback

    def rated_runs(self, *, limit: int = 100) -> list[AgentRunLog]:
        stmt = (
            select(AgentRunLog)
            .join(AgentFeedback, AgentFeedback.agent_run_id == AgentRunLog.id)
            .options(selectinload(AgentRunLog.feedback))
            .where(AgentRunLog.status == "completed")
            .order_by(AgentRunLog.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def recent_runs(self, *, limit: int = 100) -> list[AgentRunLog]:
        stmt = (
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .order_by(AgentRunLog.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def run_page(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> EvaluationRunPage:
        if page < 1:
            raise ValueError("page must be at least 1")
        if page_size < 1 or page_size > self.MAX_PAGE_SIZE:
            raise ValueError(
                f"page_size must be between 1 and {self.MAX_PAGE_SIZE}"
            )
        total = int(self.session.scalar(select(func.count(AgentRunLog.id))) or 0)
        runs = list(
            self.session.scalars(
                select(AgentRunLog)
                .options(selectinload(AgentRunLog.feedback))
                .order_by(AgentRunLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return EvaluationRunPage(
            runs=runs,
            page=page,
            page_size=page_size,
            total=total,
            has_previous=page > 1,
            has_next=page * page_size < total,
        )


    def conversation_runs(self, conversation_id: int) -> list[AgentRunLog]:
        stmt = (
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .where(AgentRunLog.conversation_id == conversation_id)
            .order_by(AgentRunLog.id.asc())
        )
        return list(self.session.scalars(stmt))

    def runs_for_assistant_messages(
        self, assistant_message_ids: Sequence[int]
    ) -> list[AgentRunLog]:
        if not assistant_message_ids:
            return []
        stmt = (
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .where(AgentRunLog.assistant_message_id.in_(assistant_message_ids))
            .order_by(AgentRunLog.id.asc())
        )
        return list(self.session.scalars(stmt))

    def iter_export_records(self) -> Iterator[EvaluationExportRecord]:
        stmt = (
            select(
                AgentRunLog.id.label("run_id"),
                AgentRunLog.conversation_id,
                AgentRunLog.prompt_version,
                AgentRunLog.prompt_hash,
                AgentRunLog.system_prompt,
                AgentRunLog.llm_provider,
                AgentRunLog.llm_model,
                AgentRunLog.llm_config,
                AgentRunLog.input_messages,
                AgentRunLog.tool_trace,
                AgentRunLog.final_content,
                AgentRunLog.rounds,
                AgentRunLog.status,
                AgentRunLog.error,
                AgentFeedback.rating,
                AgentFeedback.comment,
                AgentRunLog.created_at,
            )
            .join(AgentFeedback, AgentFeedback.agent_run_id == AgentRunLog.id)
            .where(AgentRunLog.status == "completed")
            .order_by(AgentRunLog.id.asc())
            .execution_options(yield_per=self.EXPORT_CHUNK_SIZE)
        )
        for row in self.session.execute(stmt):
            yield EvaluationExportRecord(*row)

    def summaries(self) -> list[EvaluationSummary]:
        stmt = (
            select(
                AgentRunLog.prompt_version,
                AgentRunLog.prompt_hash,
                AgentRunLog.llm_provider,
                AgentRunLog.llm_model,
                AgentRunLog.llm_config,
                func.count(AgentRunLog.id),
                func.count(AgentFeedback.id),
                func.sum(AgentFeedback.rating),
            )
            .outerjoin(AgentFeedback, AgentFeedback.agent_run_id == AgentRunLog.id)
            .group_by(
                AgentRunLog.prompt_version,
                AgentRunLog.prompt_hash,
                AgentRunLog.llm_provider,
                AgentRunLog.llm_model,
                AgentRunLog.llm_config,
            )
        )
        groups: dict[
            tuple[str, str, str, str, str],
            dict[str, Any],
        ] = {}
        config_hashes: dict[tuple[str, str, str, str, str], str] = {}
        for row in self.session.execute(stmt):
            config = dict(row.llm_config)
            canonical, config_hash = canonical_llm_config(config)
            key = (
                row.prompt_version,
                row.prompt_hash,
                row.llm_provider,
                row.llm_model,
                canonical,
            )
            group = groups.setdefault(
                key,
                {"config": config, "runs": 0, "rated_runs": 0, "rating_sum": 0},
            )
            group["runs"] += int(row[5])
            group["rated_runs"] += int(row[6])
            group["rating_sum"] += int(row[7] or 0)
            config_hashes[key] = config_hash

        summaries: list[EvaluationSummary] = []
        for key, group in groups.items():
            rated_runs = int(group["rated_runs"])
            summaries.append(
                EvaluationSummary(
                    prompt_version=key[0],
                    prompt_hash=key[1],
                    llm_provider=key[2],
                    llm_model=key[3],
                    llm_config_hash=config_hashes[key],
                    llm_config=dict(group["config"]),
                    runs=int(group["runs"]),
                    rated_runs=rated_runs,
                    average_rating=(
                        int(group["rating_sum"]) / rated_runs if rated_runs else None
                    ),
                )
            )
        return sorted(
            summaries,
            key=lambda summary: (
                summary.prompt_version,
                summary.llm_provider,
                summary.llm_model,
                summary.llm_config_hash,
            ),
        )

    @staticmethod
    def _clean_comment(comment: str | None) -> str | None:
        if comment is None:
            return None
        value = comment.strip()
        return value or None

    def _commit(self, entity: object) -> None:
        self._persist(entity, commit=True)

    def _persist(self, entity: object, *, commit: bool) -> None:
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except Exception:
            if commit:
                self.session.rollback()
            raise
        self.session.refresh(entity)
