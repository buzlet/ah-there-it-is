"""Run the versioned evaluation corpus against a configured LLM provider.

Each case receives a fresh deterministic inventory fixture. This makes prompt
and model comparisons reproducible while keeping live user data untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.agent.protocol import LLMClient
from ah_there_it_is.agent.runner import AgentRunner, SYSTEM_PROMPT
from ah_there_it_is.config import get_settings
from ah_there_it_is.db.models import AgentRunLog, Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.eval_checks import event_count, evaluate_expected_check
from ah_there_it_is.eval_corpus import EvaluationCase, load_corpus
from ah_there_it_is.eval_fixture import FIXTURE_VERSION, seed_inventory_fixture


def _load_prompt(prompt_path: str | None) -> str:
    if prompt_path:
        return Path(prompt_path).read_text(encoding="utf-8")
    settings = get_settings()
    if settings.prompt_file:
        return Path(settings.prompt_file).read_text(encoding="utf-8")
    return SYSTEM_PROMPT


def _summarize(cases: list[dict[str, Any]]) -> dict[str, int]:
    checked_cases = [case for case in cases if case["checks_passed"] is not None]
    return {
        "count": len(cases),
        "completed": sum(case["status"] == "completed" for case in cases),
        "failed": sum(case["status"] == "failed" for case in cases),
        "automatically_checked": len(checked_cases),
        "automatic_checks_passed": sum(
            case["checks_passed"] is True for case in checked_cases
        ),
        "manual_review_required": len(cases) - len(checked_cases),
    }


def _write_report(path: str, report: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_case(
    case: EvaluationCase,
    *,
    prompt: str,
    prompt_version: str,
    allow_heuristic: bool = False,
    llm_factory: Callable[[], LLMClient] | None = None,
) -> dict[str, Any]:
    case_started = time.perf_counter()
    settings = get_settings()
    if settings.llm_provider == "heuristic" and not allow_heuristic:
        raise RuntimeError(
            "live evaluation requires a configured real provider; "
            "pass --allow-heuristic only for offline plumbing checks"
        )

    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)

    try:
        with factory() as session:
            seed_inventory_fixture(session)
            events_before = event_count(session)
            provider_factory = llm_factory or build_llm_factory(settings)
            llm = provider_factory()
            runner = AgentRunner(
                session,
                llm,
                max_rounds=settings.agent_max_rounds,
                system_prompt=prompt,
                prompt_version=prompt_version,
            )
            conversation_id: int | None = None
            turns: list[dict[str, Any]] = []
            status = "completed"
            error: str | None = None

            try:
                for user_text in case.turns:
                    result = runner.run(user_text, conversation_id=conversation_id)
                    conversation_id = result.conversation_id
                    run_log = runner.evaluation.get_run(result.run_id)
                    turns.append(
                        {
                            "user": user_text,
                            "assistant": result.content,
                            "run_id": result.run_id,
                            "rounds": result.rounds,
                            "status": run_log.status,
                            "tool_trace": run_log.tool_trace,
                            "llm_provider": run_log.llm_provider,
                            "llm_model": run_log.llm_model,
                            "llm_config": run_log.llm_config,
                        }
                    )
            except Exception as exc:  # live harness must report, not hide, provider/tool failures
                status = "failed"
                error = f"{type(exc).__name__}: {exc}"
                latest = session.scalar(
                    select(AgentRunLog).order_by(AgentRunLog.id.desc()).limit(1)
                )
                if latest is not None and not any(
                    turn.get("run_id") == latest.id for turn in turns
                ):
                    turns.append(
                        {
                            "user": case.turns[len(turns)] if len(turns) < len(case.turns) else None,
                            "assistant": latest.final_content,
                            "run_id": latest.id,
                            "rounds": latest.rounds,
                            "status": latest.status,
                            "error": latest.error,
                            "tool_trace": latest.tool_trace,
                            "llm_provider": latest.llm_provider,
                            "llm_model": latest.llm_model,
                            "llm_config": latest.llm_config,
                        }
                    )

            checks = [
                evaluate_expected_check(
                    session,
                    check,
                    events_before=events_before,
                )
                for check in case.checks
            ]
            assistant_text = "\n".join(
                str(turn.get("assistant") or "") for turn in turns
            ).casefold()
            unsupported_fact_matches = [
                fact for fact in case.unsupported_facts if fact.casefold() in assistant_text
            ]
            close = getattr(llm, "close", None)
            if callable(close):
                close()
            return {
                "case_id": case.id,
                "group": case.group,
                "focus": case.focus,
                "status": status,
                "error": error,
                "turns": turns,
                "checks": checks,
                "unsupported_fact_failures": len(unsupported_fact_matches),
                "unsupported_fact_matches": unsupported_fact_matches,
                "wall_seconds": round(time.perf_counter() - case_started, 6),
                "checks_passed": (
                    status == "completed"
                    and all(check["ok"] for check in checks)
                    and not unsupported_fact_matches
                    if checks or case.unsupported_facts
                    else None
                ),
            }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="eval/corpus-v1.json")
    parser.add_argument("--prompt")
    parser.add_argument("--version", default=None)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output")
    parser.add_argument("--allow-heuristic", action="store_true")
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    if corpus.fixture != FIXTURE_VERSION:
        raise SystemExit(
            f"corpus requires fixture {corpus.fixture!r}, available {FIXTURE_VERSION!r}"
        )

    prompt = _load_prompt(args.prompt)
    settings = get_settings()
    prompt_version = args.version or settings.prompt_version
    selected = corpus.cases
    if args.case_ids:
        requested = set(args.case_ids)
        selected = [case for case in selected if case.id in requested]
        missing = requested.difference(case.id for case in selected)
        if missing:
            raise SystemExit("unknown case ids: " + ", ".join(sorted(missing)))
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be >= 1")
        selected = selected[: args.limit]

    probe = build_llm_factory(settings)()
    try:
        llm_info = probe.info
    finally:
        close = getattr(probe, "close", None)
        if callable(close):
            close()

    report: dict[str, Any] = {
        "corpus_version": corpus.version,
        "fixture_version": FIXTURE_VERSION,
        "prompt_version": prompt_version,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "provider": llm_info.model_dump(mode="json"),
        "cases": [],
        "summary": _summarize([]),
    }
    if args.output:
        _write_report(args.output, report)

    total = len(selected)
    for index, case in enumerate(selected, start=1):
        print(
            f"[live-eval] case {index}/{total} start {case.id}",
            flush=True,
        )
        result = run_case(
            case,
            prompt=prompt,
            prompt_version=prompt_version,
            allow_heuristic=args.allow_heuristic,
        )
        report["cases"].append(result)
        report["summary"] = _summarize(report["cases"])
        if args.output:
            _write_report(args.output, report)
        rounds = sum(turn.get("rounds", 0) for turn in result["turns"])
        error_suffix = f" error={result['error']}" if result["error"] else ""
        print(
            f"[live-eval] case {index}/{total} done {case.id} "
            f"status={result['status']} rounds={rounds} "
            f"wall={result['wall_seconds']:.3f}s{error_suffix}",
            flush=True,
        )

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if not args.output:
        print(rendered)

    if report["summary"]["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
