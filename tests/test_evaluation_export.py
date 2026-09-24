from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import StringIO
import json

from sqlalchemy import event
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import AgentFeedback, AgentRunLog
from ah_there_it_is.evaluation_export import write_evaluation_json
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import (
    EvaluationExportRecord,
    EvaluationService,
)


EXPECTED_KEYS = {
    "run_id",
    "conversation_id",
    "prompt_version",
    "prompt_hash",
    "system_prompt",
    "llm_provider",
    "llm_model",
    "llm_config",
    "input_messages",
    "tool_trace",
    "final_content",
    "rounds",
    "status",
    "error",
    "rating",
    "comment",
    "created_at",
}


def _projection(run_id: int, text: str = "Ответ") -> EvaluationExportRecord:
    return EvaluationExportRecord(
        run_id=run_id,
        conversation_id=7,
        prompt_version="export-v1",
        prompt_hash="a" * 64,
        system_prompt="Системный промпт",
        llm_provider="test",
        llm_model="streaming",
        llm_config={"temperature": 0},
        input_messages=[{"role": "user", "content": "Где тестер?"}],
        tool_trace=[{"tool_results": []}],
        final_content=text,
        rounds=1,
        status="completed",
        error=None,
        rating=5,
        comment="точно",
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )


def test_writer_emits_empty_unicode_and_exact_record_contract() -> None:
    empty = StringIO()
    write_evaluation_json(iter(()), empty)
    assert empty.getvalue() == "[]\n"
    assert json.loads(empty.getvalue()) == []

    output = StringIO()
    write_evaluation_json([_projection(1, "Привет, мир")], output)
    records = json.loads(output.getvalue())
    assert len(records) == 1
    assert set(records[0]) == EXPECTED_KEYS
    assert records[0]["final_content"] == "Привет, мир"
    assert "Привет, мир" in output.getvalue()
    assert output.getvalue().endswith("\n")


def test_writer_requests_records_lazily_and_has_no_application_cap() -> None:
    output = StringIO()

    def records():
        yield _projection(1)
        assert '"run_id": 1' in output.getvalue()
        for run_id in range(2, 1002):
            yield _projection(run_id)

    write_evaluation_json(records(), output)
    parsed = json.loads(output.getvalue())
    assert len(parsed) == 1001
    assert [parsed[0]["run_id"], parsed[-1]["run_id"]] == [1, 1001]


def test_export_projection_filters_orders_and_uses_one_uncapped_query(
    session: Session,
) -> None:
    conversation_id = ConversationService(session).create().id
    started = datetime(2020, 1, 1, tzinfo=timezone.utc)
    run_count = 1205
    session.execute(
        AgentRunLog.__table__.insert(),
        [
            {
                "id": run_id,
                "conversation_id": conversation_id,
                "user_message_id": None,
                "assistant_message_id": None,
                "prompt_version": "bulk-v1",
                "prompt_hash": "b" * 64,
                "system_prompt": "bulk",
                "llm_provider": "test",
                "llm_model": "streaming",
                "llm_config": {"temperature": run_id % 2},
                "input_messages": [{"content": f"input-{run_id}"}],
                "tool_trace": [{"tool_results": []}],
                "mutation_receipts": [],
                "final_content": f"answer-{run_id}",
                "rounds": 1,
                "status": "failed" if run_id == run_count else "completed",
                "error": "failed" if run_id == run_count else None,
                "created_at": started + timedelta(seconds=run_id),
            }
            for run_id in range(1, run_count + 1)
        ],
    )
    session.execute(
        AgentFeedback.__table__.insert(),
        [
            {
                "id": run_id,
                "agent_run_id": run_id,
                "rating": (run_id % 5) + 1,
                "comment": "оценка" if run_id == 1 else None,
                "created_at": started,
                "updated_at": started,
            }
            for run_id in range(1, 1201)
        ]
        + [
            {
                "id": run_count,
                "agent_run_id": run_count,
                "rating": 1,
                "comment": "failed must not export",
                "created_at": started,
                "updated_at": started,
            }
        ],
    )
    session.commit()
    session.expunge_all()

    statements: list[str] = []
    engine = session.get_bind()
    listener = lambda _connection, _cursor, statement, *_args: statements.append(statement)
    event.listen(engine, "before_cursor_execute", listener)
    records = list(EvaluationService(session).iter_export_records())
    event.remove(engine, "before_cursor_execute", listener)

    assert len(records) == 1200
    assert records[0].run_id == 1 and records[-1].run_id == 1200
    assert records[0].comment == "оценка"
    assert len(statements) == 1
    assert "LIMIT" not in statements[0].upper()
    assert "100000" not in statements[0]
    assert not any(
        isinstance(instance, (AgentRunLog, AgentFeedback))
        for instance in session.identity_map.values()
    )


def test_projection_with_no_rated_runs_writes_empty_array(session: Session) -> None:
    output = StringIO()
    write_evaluation_json(EvaluationService(session).iter_export_records(), output)
    assert json.loads(output.getvalue()) == []
