"""Prompt/model experiment persistence, replay metrics, and human review."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import (
    AgentRunLog,
    ExperimentReview,
    ExperimentRun,
    utc_now,
)
from ah_there_it_is.domain.exceptions import EntityNotFoundError
from ah_there_it_is.services.evaluation import canonical_llm_config

_MUTATION_TOOLS = {"create_item", "create_location", "create_category", "update_item", "move_item"}
_REVIEW_CHOICES = {"baseline", "variant", "tie", "both_bad"}


@dataclass(frozen=True)
class ExperimentSummary:
    experiment_name: str
    prompt_version: str
    prompt_hash: str
    llm_provider: str
    llm_model: str
    llm_config_hash: str
    llm_config: dict[str, Any]
    cases: int
    completed: int
    diverged: int
    failed: int
    average_rounds: float
    source_average_rating: float | None
    reviewed: int
    variant_average_rating: float | None
    baseline_wins: int
    variant_wins: int
    ties: int
    both_bad: int
    clarification_rate: float
    tool_error_rate: float
    mutation_error_rate: float


class ExperimentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_run(
        self,
        *,
        source_run_id: int,
        experiment_name: str,
        prompt_version: str,
        prompt_hash: str,
        system_prompt: str,
        llm_provider: str,
        llm_model: str,
        llm_config: dict[str, Any],
        input_messages: list[dict[str, Any]],
        tool_trace: list[dict[str, Any]],
        final_content: str | None,
        rounds: int,
        status: str,
        error: str | None = None,
        divergence_reason: str | None = None,
    ) -> ExperimentRun:
        self._require_source(source_run_id)
        run = ExperimentRun(
            source_run_id=source_run_id,
            experiment_name=experiment_name.strip(),
            prompt_version=prompt_version.strip(),
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
            divergence_reason=divergence_reason,
        )
        self.session.add(run)
        self._commit(run)
        return run

    def get_run(self, run_id: int) -> ExperimentRun:
        stmt = (
            select(ExperimentRun)
            .options(
                selectinload(ExperimentRun.review),
                selectinload(ExperimentRun.source_run).selectinload(AgentRunLog.feedback),
            )
            .where(ExperimentRun.id == run_id)
        )
        run = self.session.scalar(stmt)
        if run is None:
            raise EntityNotFoundError(f"experiment run id={run_id} does not exist")
        return run

    def recent_runs(self, *, limit: int = 100) -> list[ExperimentRun]:
        stmt = (
            select(ExperimentRun)
            .options(
                selectinload(ExperimentRun.review),
                selectinload(ExperimentRun.source_run).selectinload(AgentRunLog.feedback),
            )
            .order_by(ExperimentRun.id.desc())
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def set_review(
        self,
        run_id: int,
        *,
        choice: str,
        variant_rating: int | None = None,
        comment: str | None = None,
    ) -> ExperimentReview:
        if choice not in _REVIEW_CHOICES:
            raise ValueError(f"choice must be one of {sorted(_REVIEW_CHOICES)}")
        if variant_rating is not None and not 1 <= variant_rating <= 5:
            raise ValueError("variant_rating must be between 1 and 5")
        run = self.get_run(run_id)
        review = run.review
        if review is None:
            review = ExperimentReview(
                experiment_run=run,
                choice=choice,
                variant_rating=variant_rating,
                comment=self._clean_comment(comment),
            )
            self.session.add(review)
        else:
            review.choice = choice
            review.variant_rating = variant_rating
            review.comment = self._clean_comment(comment)
            review.updated_at = utc_now()
        self._commit(review)
        return review

    def summaries(self) -> list[ExperimentSummary]:
        runs = self.recent_runs(limit=10_000)
        groups: dict[
            tuple[str, str, str, str, str, str],
            list[ExperimentRun],
        ] = {}
        config_hashes: dict[
            tuple[str, str, str, str, str, str],
            str,
        ] = {}
        for run in runs:
            canonical, config_hash = canonical_llm_config(run.llm_config)
            key = (
                run.experiment_name,
                run.prompt_version,
                run.prompt_hash,
                run.llm_provider,
                run.llm_model,
                canonical,
            )
            groups.setdefault(key, []).append(run)
            config_hashes[key] = config_hash

        summaries: list[ExperimentSummary] = []
        for key, group in groups.items():
            source_ratings = [
                run.source_run.feedback.rating
                for run in group
                if run.source_run.feedback is not None
            ]
            variant_ratings = [
                run.review.variant_rating
                for run in group
                if run.review is not None and run.review.variant_rating is not None
            ]
            choices = [run.review.choice for run in group if run.review is not None]
            summaries.append(
                ExperimentSummary(
                    experiment_name=key[0],
                    prompt_version=key[1],
                    prompt_hash=key[2],
                    llm_provider=key[3],
                    llm_model=key[4],
                    llm_config_hash=config_hashes[key],
                    llm_config=dict(group[0].llm_config),
                    cases=len(group),
                    completed=sum(run.status == "completed" for run in group),
                    diverged=sum(run.status == "diverged" for run in group),
                    failed=sum(run.status == "failed" for run in group),
                    average_rounds=mean(run.rounds for run in group),
                    source_average_rating=(mean(source_ratings) if source_ratings else None),
                    reviewed=len(choices),
                    variant_average_rating=(mean(variant_ratings) if variant_ratings else None),
                    baseline_wins=choices.count("baseline"),
                    variant_wins=choices.count("variant"),
                    ties=choices.count("tie"),
                    both_bad=choices.count("both_bad"),
                    clarification_rate=self._rate(group, self._is_clarification),
                    tool_error_rate=self._rate(group, self._has_tool_error),
                    mutation_error_rate=self._rate(group, self._has_mutation_error),
                )
            )
        return sorted(summaries, key=lambda summary: summary.experiment_name)

    def _require_source(self, source_run_id: int) -> AgentRunLog:
        source = self.session.get(AgentRunLog, source_run_id)
        if source is None:
            raise EntityNotFoundError(f"agent run id={source_run_id} does not exist")
        return source

    @staticmethod
    def _is_clarification(run: ExperimentRun) -> bool:
        content = (run.final_content or "").strip().casefold()
        return run.status == "completed" and (
            content.endswith("?")
            or "уточн" in content
            or "which one" in content
            or "clarify" in content
        )

    @staticmethod
    def _has_tool_error(run: ExperimentRun) -> bool:
        return any(
            isinstance(entry.get("result"), dict) and not entry["result"].get("ok", False)
            for round_trace in run.tool_trace
            for entry in round_trace.get("tool_results", [])
        )

    @staticmethod
    def _has_mutation_error(run: ExperimentRun) -> bool:
        return any(
            entry.get("tool_name") in _MUTATION_TOOLS
            and isinstance(entry.get("result"), dict)
            and not entry["result"].get("ok", False)
            for round_trace in run.tool_trace
            for entry in round_trace.get("tool_results", [])
        )

    @staticmethod
    def _rate(group: list[ExperimentRun], predicate) -> float:
        return sum(bool(predicate(run)) for run in group) / len(group) if group else 0.0

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
