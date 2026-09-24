"""Export rated agent runs as JSON for later prompt/model replay experiments."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from typing import Any, TextIO

from ah_there_it_is.config import get_settings
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.evaluation import (
    EvaluationExportRecord,
    EvaluationService,
)


def _record_dict(record: EvaluationExportRecord) -> dict[str, Any]:
    return {
        "run_id": record.run_id,
        "conversation_id": record.conversation_id,
        "prompt_version": record.prompt_version,
        "prompt_hash": record.prompt_hash,
        "system_prompt": record.system_prompt,
        "llm_provider": record.llm_provider,
        "llm_model": record.llm_model,
        "llm_config": record.llm_config,
        "input_messages": record.input_messages,
        "tool_trace": record.tool_trace,
        "final_content": record.final_content,
        "rounds": record.rounds,
        "status": record.status,
        "error": record.error,
        "rating": record.rating,
        "comment": record.comment,
        "created_at": record.created_at.isoformat(),
    }


def write_evaluation_json(
    records: Iterable[EvaluationExportRecord], stream: TextIO
) -> None:
    stream.write("[")
    first = True
    for record in records:
        if first:
            first = False
        else:
            stream.write(",")
        stream.write("\n  ")
        stream.write(json.dumps(_record_dict(record), ensure_ascii=False))
    if not first:
        stream.write("\n")
    stream.write("]\n")


def main() -> int:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            write_evaluation_json(
                EvaluationService(session).iter_export_records(), sys.stdout
            )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
