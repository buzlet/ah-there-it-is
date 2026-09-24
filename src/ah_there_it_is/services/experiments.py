"""Prompt/model experiment persistence, replay metrics, and human review."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ah_there_it_is.db.models import (
    AgentRunLog,
    AgentFeedback,
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


@dataclass(frozen=True)
class ExperimentRunPage:
    runs: list[ExperimentRun]
    page: int
    page_size: int
    total: int
    has_previous: bool
    has_next: bool


class ExperimentService:
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100

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

    def run_page(
        self,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> ExperimentRunPage:
        if page < 1:
            raise ValueError("page must be at least 1")
        if page_size < 1 or page_size > self.MAX_PAGE_SIZE:
            raise ValueError(
                f"page_size must be between 1 and {self.MAX_PAGE_SIZE}"
            )
        total = int(self.session.scalar(select(func.count(ExperimentRun.id))) or 0)
        runs = list(
            self.session.scalars(
                select(ExperimentRun)
                .options(
                    selectinload(ExperimentRun.review),
                    selectinload(ExperimentRun.source_run).selectinload(
                        AgentRunLog.feedback
                    ),
                )
                .order_by(ExperimentRun.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return ExperimentRunPage(
            runs=runs,
            page=page,
            page_size=page_size,
            total=total,
            has_previous=page > 1,
            has_next=page * page_size < total,
        )

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
        stmt = (
            select(
                ExperimentRun.experiment_name,
                ExperimentRun.prompt_version,
                ExperimentRun.prompt_hash,
                ExperimentRun.llm_provider,
                ExperimentRun.llm_model,
                ExperimentRun.llm_config,
                ExperimentRun.status,
                ExperimentRun.rounds,
                ExperimentRun.final_content,
                ExperimentRun.tool_trace,
                AgentFeedback.rating.label("source_rating"),
                ExperimentReview.choice,
                ExperimentReview.variant_rating,
            )
            .join(AgentRunLog, AgentRunLog.id == ExperimentRun.source_run_id)
            .outerjoin(AgentFeedback, AgentFeedback.agent_run_id == AgentRunLog.id)
            .outerjoin(
                ExperimentReview,
                ExperimentReview.experiment_run_id == ExperimentRun.id,
            )
            .order_by(ExperimentRun.id.asc())
            .execution_options(yield_per=500)
        )
        groups: dict[
            tuple[str, str, str, str, str, str],
            dict[str, Any],
        ] = {}
        config_hashes: dict[
            tuple[str, str, str, str, str, str],
            str,
        ] = {}
        for row in self.session.execute(stmt):
            config = dict(row.llm_config)
            canonical, config_hash = canonical_llm_config(config)
            key = (
                row.experiment_name,
                row.prompt_version,
                row.prompt_hash,
                row.llm_provider,
                row.llm_model,
                canonical,
            )
            group = groups.setdefault(
                key,
                {
                    "config": config,
                    "cases": 0,
                    "completed": 0,
                    "diverged": 0,
                    "failed": 0,
                    "rounds": 0,
                    "source_rating_sum": 0,
                    "source_rated": 0,
                    "reviewed": 0,
                    "variant_rating_sum": 0,
                    "variant_rated": 0,
                    "baseline": 0,
                    "variant": 0,
                    "tie": 0,
                    "both_bad": 0,
                    "clarifications": 0,
                    "tool_errors": 0,
                    "mutation_errors": 0,
                },
            )
            group["cases"] += 1
            group[row.status] += 1
            group["rounds"] += row.rounds
            if row.source_rating is not None:
                group["source_rating_sum"] += row.source_rating
                group["source_rated"] += 1
            if row.choice is not None:
                group["reviewed"] += 1
                group[row.choice] += 1
            if row.variant_rating is not None:
                group["variant_rating_sum"] += row.variant_rating
                group["variant_rated"] += 1
            group["clarifications"] += self._is_clarification(row)
            group["tool_errors"] += self._has_tool_error(row)
            group["mutation_errors"] += self._has_mutation_error(row)
            config_hashes[key] = config_hash

        summaries: list[ExperimentSummary] = []
        for key, group in groups.items():
            cases = int(group["cases"])
            source_rated = int(group["source_rated"])
            variant_rated = int(group["variant_rated"])
            summaries.append(
                ExperimentSummary(
                    experiment_name=key[0],
                    prompt_version=key[1],
                    prompt_hash=key[2],
                    llm_provider=key[3],
                    llm_model=key[4],
                    llm_config_hash=config_hashes[key],
                    llm_config=dict(group["config"]),
                    cases=cases,
                    completed=int(group["completed"]),
                    diverged=int(group["diverged"]),
                    failed=int(group["failed"]),
                    average_rounds=int(group["rounds"]) / cases,
                    source_average_rating=(
                        int(group["source_rating_sum"]) / source_rated
                        if source_rated else None
                    ),
                    reviewed=int(group["reviewed"]),
                    variant_average_rating=(
                        int(group["variant_rating_sum"]) / variant_rated
                        if variant_rated else None
                    ),
                    baseline_wins=int(group["baseline"]),
                    variant_wins=int(group["variant"]),
                    ties=int(group["tie"]),
                    both_bad=int(group["both_bad"]),
                    clarification_rate=int(group["clarifications"]) / cases,
                    tool_error_rate=int(group["tool_errors"]) / cases,
                    mutation_error_rate=int(group["mutation_errors"]) / cases,
                )
            )
        return sorted(
            summaries,
            key=lambda summary: (
                summary.experiment_name,
                summary.prompt_version,
                summary.prompt_hash,
                summary.llm_provider,
                summary.llm_model,
                summary.llm_config_hash,
            ),
        )

    def _require_source(self, source_run_id: int) -> AgentRunLog:
        source = self.session.get(AgentRunLog, source_run_id)
        if source is None:
            raise EntityNotFoundError(f"agent run id={source_run_id} does not exist")
        return source

    @staticmethod
    def _is_clarification(run: Any) -> bool:
        content = (run.final_content or "").strip().casefold()
        return run.status == "completed" and (
            content.endswith("?")
            or "уточн" in content
            or "which one" in content
            or "clarify" in content
        )

    @staticmethod
    def _has_tool_error(run: Any) -> bool:
        return any(
            isinstance(entry.get("result"), dict) and not entry["result"].get("ok", False)
            for round_trace in run.tool_trace
            for entry in round_trace.get("tool_results", [])
        )

    @staticmethod
    def _has_mutation_error(run: Any) -> bool:
        return any(
            entry.get("tool_name") in _MUTATION_TOOLS
            and isinstance(entry.get("result"), dict)
            and not entry["result"].get("ok", False)
            for round_trace in run.tool_trace
            for entry in round_trace.get("tool_results", [])
        )

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
