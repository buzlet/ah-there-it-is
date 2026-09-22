"""Run deterministic application scenarios with a scenario-driven mock LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.agent.scenario_mock import (
    ScenarioCase,
    ScenarioLLMClient,
    load_scenario_suite,
)
from ah_there_it_is.db.models import AgentRunLog, Base
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.eval_checks import event_count, evaluate_checks
from ah_there_it_is.eval_corpus import EvaluationCase, load_corpus
from ah_there_it_is.eval_fixture import FIXTURE_VERSION, seed_inventory_fixture


SCENARIO_PROMPT = (
    "Deterministic scenario mock for application-pipeline testing. "
    "Natural-language reasoning is intentionally outside this pipeline."
)


def _run_case(case: EvaluationCase, scenario: ScenarioCase) -> dict[str, Any]:
    engine = create_db_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)

    turns: list[dict[str, Any]] = []
    try:
        with factory() as session:
            seed_inventory_fixture(session)
            events_before = event_count(session)
            llm = ScenarioLLMClient(scenario)
            runner = AgentRunner(
                session,
                llm,
                max_rounds=32,
                system_prompt=SCENARIO_PROMPT,
                prompt_version="scenario-mock-v1",
            )
            conversation_id: int | None = None

            try:
                for user_text in case.turns:
                    result = runner.run(user_text, conversation_id=conversation_id)
                    conversation_id = result.conversation_id
                    run_log = runner.evaluation.get_run(result.run_id)
                    turns.append(
                        {
                            "user": user_text,
                            "assistant": result.content,
                            "rounds": result.rounds,
                            "status": run_log.status,
                            "tool_trace": run_log.tool_trace,
                        }
                    )

                llm.assert_exhausted()
                checks = evaluate_checks(
                    session,
                    case.checks,
                    events_before=events_before,
                )
                return {
                    "case_id": case.id,
                    "status": "completed",
                    "turns": turns,
                    "checks": checks,
                    "checks_passed": (
                        all(check["ok"] for check in checks) if checks else None
                    ),
                }
            except Exception as exc:
                latest = session.scalar(
                    select(AgentRunLog).order_by(AgentRunLog.id.desc()).limit(1)
                )
                if latest is not None and not any(
                    turn.get("run_id") == latest.id for turn in turns
                ):
                    turns.append(
                        {
                            "user": (
                                case.turns[len(turns)]
                                if len(turns) < len(case.turns)
                                else None
                            ),
                            "assistant": latest.final_content,
                            "run_id": latest.id,
                            "rounds": latest.rounds,
                            "status": latest.status,
                            "error": latest.error,
                            "tool_trace": latest.tool_trace,
                        }
                    )
                return {
                    "case_id": case.id,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "turns": turns,
                    "checks": [],
                    "checks_passed": False,
                }
    finally:
        engine.dispose()


def run_suite(
    *,
    corpus_path: str | Path,
    scenarios_path: str | Path,
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    corpus = load_corpus(corpus_path)
    suite = load_scenario_suite(scenarios_path)
    if corpus.fixture != FIXTURE_VERSION:
        raise ValueError(
            f"corpus requires fixture {corpus.fixture!r}, available {FIXTURE_VERSION!r}"
        )
    if suite.corpus_version != corpus.version:
        raise ValueError(
            f"scenario suite targets {suite.corpus_version!r}, "
            f"loaded corpus is {corpus.version!r}"
        )

    corpus_by_id = {case.id: case for case in corpus.cases}
    scenario_by_id = {case.case_id: case for case in suite.cases}
    missing_corpus = sorted(set(scenario_by_id) - set(corpus_by_id))
    if missing_corpus:
        raise ValueError(
            "scenario ids missing from corpus: " + ", ".join(missing_corpus)
        )

    selected_ids = case_ids or [case.case_id for case in suite.cases]
    missing_scenarios = sorted(set(selected_ids) - set(scenario_by_id))
    if missing_scenarios:
        raise ValueError(
            "case ids missing from scenario suite: " + ", ".join(missing_scenarios)
        )

    results = [
        _run_case(corpus_by_id[case_id], scenario_by_id[case_id])
        for case_id in selected_ids
    ]
    return {
        "pipeline": "application-scenario-mock",
        "scenario_version": suite.version,
        "corpus_version": corpus.version,
        "fixture_version": FIXTURE_VERSION,
        "cases": results,
        "summary": {
            "count": len(results),
            "completed": sum(case["status"] == "completed" for case in results),
            "failed": sum(case["status"] == "failed" for case in results),
            "checks_passed": sum(
                case["checks_passed"] is True for case in results
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="eval/corpus-v1.json")
    parser.add_argument("--scenarios", default="eval/scenarios-v1.json")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--output")
    args = parser.parse_args()

    report = run_suite(
        corpus_path=args.corpus,
        scenarios_path=args.scenarios,
        case_ids=args.case_ids,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if report["summary"]["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
