"""Agent run logging and user feedback for prompt/model evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
    runs: int
    rated_runs: int
    average_rating: float | None


class EvaluationService:
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
        final_content: str | None,
        rounds: int,
        status: str,
        error: str | None = None,
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
            final_content=final_content,
            rounds=rounds,
            status=status,
            error=error,
        )
        self.session.add(run)
        self._commit(run)
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

    def recent_runs(self, *, limit: int = 100) -> list[AgentRunLog]:
        stmt = (
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .order_by(AgentRunLog.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))


    def conversation_runs(self, conversation_id: int) -> list[AgentRunLog]:
        stmt = (
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .where(AgentRunLog.conversation_id == conversation_id)
            .order_by(AgentRunLog.id.asc())
        )
        return list(self.session.scalars(stmt))

    def summaries(self) -> list[EvaluationSummary]:
        stmt = (
            select(
                AgentRunLog.prompt_version,
                AgentRunLog.prompt_hash,
                AgentRunLog.llm_provider,
                AgentRunLog.llm_model,
                func.count(AgentRunLog.id),
                func.count(AgentFeedback.id),
                func.avg(AgentFeedback.rating),
            )
            .outerjoin(AgentFeedback, AgentFeedback.agent_run_id == AgentRunLog.id)
            .group_by(
                AgentRunLog.prompt_version,
                AgentRunLog.prompt_hash,
                AgentRunLog.llm_provider,
                AgentRunLog.llm_model,
            )
            .order_by(AgentRunLog.prompt_version, AgentRunLog.llm_provider, AgentRunLog.llm_model)
        )
        return [
            EvaluationSummary(
                prompt_version=row[0],
                prompt_hash=row[1],
                llm_provider=row[2],
                llm_model=row[3],
                runs=int(row[4]),
                rated_runs=int(row[5]),
                average_rating=float(row[6]) if row[6] is not None else None,
            )
            for row in self.session.execute(stmt)
        ]

    @staticmethod
    def _clean_comment(comment: str | None) -> str | None:
        if comment is None:
            return None
        value = comment.strip()
        return value or None

    def _commit(self, entity: object) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(entity)
