"""CLI for replaying rated historical runs against a prompt/model variant."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ah_there_it_is.agent.experiments import ExperimentRunner
from ah_there_it_is.agent.factory import build_llm_factory
from ah_there_it_is.config import get_settings
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.experiments import ExperimentService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Experiment label, e.g. strict-v2")
    parser.add_argument("--prompt", required=True, help="Path to the variant system prompt")
    parser.add_argument("--version", required=True, help="Human-readable prompt version")
    parser.add_argument("--source-run-id", type=int, action="append", default=[])
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    settings = get_settings()
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    llm_factory = build_llm_factory(settings)

    try:
        with factory() as session:
            evaluations = EvaluationService(session)
            if args.source_run_id:
                sources = [evaluations.get_run(run_id) for run_id in args.source_run_id]
            else:
                sources = evaluations.rated_runs(limit=args.limit)
            results = []
            for source in sources:
                llm = llm_factory()
                try:
                    result = ExperimentRunner(
                        session,
                        llm,
                        max_rounds=settings.agent_max_rounds,
                    ).run(
                        source,
                        experiment_name=args.name,
                        system_prompt=prompt,
                        prompt_version=args.version,
                    )
                finally:
                    close = getattr(llm, "close", None)
                    if callable(close):
                        close()
                results.append(
                    {
                        "source_run_id": source.id,
                        "experiment_run_id": result.experiment_run_id,
                        "status": result.status,
                        "rounds": result.rounds,
                        "divergence_reason": result.divergence_reason,
                    }
                )
            summaries = [
                summary.__dict__
                for summary in ExperimentService(session).summaries()
                if summary.experiment_name == args.name
            ]
        print(json.dumps({"runs": results, "summaries": summaries}, ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
