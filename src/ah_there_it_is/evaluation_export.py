"""Export rated agent runs as JSON for later prompt/model replay experiments."""

from __future__ import annotations

import json
import sys

from ah_there_it_is.config import get_settings
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.evaluation import EvaluationService


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            runs = EvaluationService(session).recent_runs(limit=100_000)
            records = [
                {
                    "run_id": run.id,
                    "conversation_id": run.conversation_id,
                    "prompt_version": run.prompt_version,
                    "prompt_hash": run.prompt_hash,
                    "system_prompt": run.system_prompt,
                    "llm_provider": run.llm_provider,
                    "llm_model": run.llm_model,
                    "llm_config": run.llm_config,
                    "input_messages": run.input_messages,
                    "tool_trace": run.tool_trace,
                    "final_content": run.final_content,
                    "rounds": run.rounds,
                    "status": run.status,
                    "error": run.error,
                    "rating": run.feedback.rating if run.feedback else None,
                    "comment": run.feedback.comment if run.feedback else None,
                    "created_at": run.created_at.isoformat(),
                }
                for run in reversed(runs)
                if run.feedback is not None
            ]
        json.dump(records, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
