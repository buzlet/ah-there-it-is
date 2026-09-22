"""Agent run logging and user feedback for prompt/model evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from sqlalchemy import select
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
            select(AgentRunLog)
            .options(selectinload(AgentRunLog.feedback))
            .order_by(AgentRunLog.id.asc())
        )
        runs = list(self.session.scalars(stmt))
        groups: dict[
            tuple[str, str, str, str, str],
            list[AgentRunLog],
        ] = {}
        config_hashes: dict[tuple[str, str, str, str, str], str] = {}
        for run in runs:
            canonical, config_hash = canonical_llm_config(run.llm_config)
            key = (
                run.prompt_version,
                run.prompt_hash,
                run.llm_provider,
                run.llm_model,
                canonical,
            )
            groups.setdefault(key, []).append(run)
            config_hashes[key] = config_hash

        summaries: list[EvaluationSummary] = []
        for key, group in groups.items():
            ratings = [
                run.feedback.rating
                for run in group
                if run.feedback is not None
            ]
            summaries.append(
                EvaluationSummary(
                    prompt_version=key[0],
                    prompt_hash=key[1],
                    llm_provider=key[2],
                    llm_model=key[3],
                    llm_config_hash=config_hashes[key],
                    llm_config=dict(group[0].llm_config),
                    runs=len(group),
                    rated_runs=len(ratings),
                    average_rating=(
                        sum(ratings) / len(ratings) if ratings else None
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
