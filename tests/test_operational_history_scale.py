from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.app import create_app
from ah_there_it_is.config import Settings
from ah_there_it_is.db.models import (
    AgentFeedback,
    AgentRunLog,
    Base,
    ChatRequestRecord,
    Conversation,
    Event,
    ExperimentReview,
    ExperimentRun,
    Message,
)
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.experiments import ExperimentService


@pytest.fixture(scope="module")
def history_store(tmp_path_factory):
    database = tmp_path_factory.mktemp("operational-history") / "history.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)
    started = datetime(2020, 1, 1, tzinfo=timezone.utc)

    with factory() as session:
        session.execute(
            Conversation.__table__.insert(),
            [{"id": 1, "created_at": started, "updated_at": started}],
        )
        session.execute(
            Message.__table__.insert(),
            [
                {
                    "id": index,
                    "conversation_id": 1,
                    "role": "assistant" if index % 2 == 0 else "user",
                    "content": f"history-message-{index:04d}",
                    "created_at": started + timedelta(seconds=index),
                }
                for index in range(1, 1001)
            ],
        )
        session.execute(
            AgentRunLog.__table__.insert(),
            [
                {
                    "id": index,
                    "conversation_id": 1,
                    "user_message_id": None,
                    "assistant_message_id": index * 2 if index <= 500 else None,
                    "prompt_version": f"scale-v{index % 2}",
                    "prompt_hash": str(index % 2) * 64,
                    "system_prompt": "scale",
                    "llm_provider": "test",
                    "llm_model": "scale-model",
                    "llm_config": {"temperature": index % 2},
                    "input_messages": [{"content": "heavy"}],
                    "tool_trace": [{"tool_results": []}],
                    "mutation_receipts": [],
                    "final_content": f"run-{index}",
                    "rounds": 1,
                    "status": "completed",
                    "error": None,
                    "created_at": started + timedelta(seconds=index),
                }
                for index in range(1, 1001)
            ],
        )
        session.execute(
            AgentFeedback.__table__.insert(),
            [
                {
                    "id": index,
                    "agent_run_id": index,
                    "rating": (index % 5) + 1,
                    "comment": None,
                    "created_at": started,
                    "updated_at": started,
                }
                for index in range(1, 1001)
            ],
        )
        session.execute(
            ExperimentRun.__table__.insert(),
            [
                {
                    "id": index,
                    "source_run_id": index,
                    "experiment_name": "scale-experiment",
                    "prompt_version": "scale-v3",
                    "prompt_hash": "e" * 64,
                    "system_prompt": "scale experiment",
                    "llm_provider": "test",
                    "llm_model": "scale-model",
                    "llm_config": {"temperature": 0},
                    "input_messages": [{"content": "heavy"}],
                    "tool_trace": [{"tool_results": []}],
                    "final_content": f"variant-{index}",
                    "rounds": 2,
                    "status": "completed",
                    "error": None,
                    "divergence_reason": None,
                    "created_at": started + timedelta(seconds=index),
                }
                for index in range(1, 1001)
            ],
        )
        session.execute(
            ExperimentReview.__table__.insert(),
            [
                {
                    "id": index,
                    "experiment_run_id": index,
                    "choice": "variant" if index % 2 else "baseline",
                    "variant_rating": (index % 5) + 1,
                    "comment": None,
                    "created_at": started,
                    "updated_at": started,
                }
                for index in range(1, 1001)
            ],
        )
        session.execute(
            ChatRequestRecord.__table__.insert(),
            [
                {
                    "id": index,
                    "request_key": f"scale-request-{index:04d}",
                    "requested_conversation_id": 1,
                    "message": f"request-{index}",
                    "status": "failed",
                    "agent_run_id": None,
                    "error": "scale fixture",
                    "recovered_from_id": 1 if index > 1 else None,
                    "recovery_note": "verified" if index > 1 else None,
                    "created_at": started + timedelta(seconds=index),
                    "updated_at": started + timedelta(seconds=index),
                }
                for index in range(1, 1001)
            ],
        )
        session.commit()

    app = create_app(
        Settings(app_name="Scale Inventory"),
        session_factory=factory,
    )
    yield factory, app, engine
    engine.dispose()


def test_scale_fixture_and_conversation_window_are_bounded(history_store) -> None:
    factory, _, engine = history_store
    with factory() as session:
        assert session.scalar(select(func.count(Message.id))) == 1000
        loaded_messages: list[Message] = []
        statements: list[str] = []

        def on_load(_session, instance) -> None:
            if isinstance(instance, Message):
                loaded_messages.append(instance)

        def on_statement(_connection, _cursor, statement, *_args) -> None:
            statements.append(statement)

        event.listen(session, "loaded_as_persistent", on_load)
        event.listen(engine, "before_cursor_execute", on_statement)
        window = ConversationService(session).message_window(1)
        assistant_ids = [row.id for row in window.messages if row.role == "assistant"]
        runs = EvaluationService(session).runs_for_assistant_messages(assistant_ids)
        event.remove(session, "loaded_as_persistent", on_load)
        event.remove(engine, "before_cursor_execute", on_statement)

        assert len(window.messages) == 50 and window.has_older is True
        assert window.messages[0].id == 951 and window.messages[-1].id == 1000
        assert len(loaded_messages) <= 51
        assert len(runs) == 25
        assert len(statements) <= 5

        older = ConversationService(session).message_window(
            1, limit=50, before_id=window.next_before_id
        )
        assert older.messages[0].id == 901 and older.messages[-1].id == 950
        assert not ({row.id for row in window.messages} & {row.id for row in older.messages})


def test_evaluation_and_experiment_scale_reads_do_not_materialize_history(
    history_store,
) -> None:
    factory, _, _ = history_store
    with factory() as session:
        evaluation_page = EvaluationService(session).run_page(page=1)
        assert len(evaluation_page.runs) == 50 and evaluation_page.total == 1000
        session.expunge_all()
        evaluation_summaries = EvaluationService(session).summaries()
        assert sum(summary.runs for summary in evaluation_summaries) == 1000
        assert not any(isinstance(row, AgentRunLog) for row in session.identity_map.values())

        experiment_page = ExperimentService(session).run_page(page=1)
        assert len(experiment_page.runs) == 50 and experiment_page.total == 1000
        session.expunge_all()
        experiment_summaries = ExperimentService(session).summaries()
        assert sum(summary.cases for summary in experiment_summaries) == 1000
        assert not any(
            isinstance(row, (ExperimentRun, AgentRunLog))
            for row in session.identity_map.values()
        )


def test_chat_request_scale_page_has_constant_query_count(history_store) -> None:
    factory, _, engine = history_store
    with factory() as session:
        statements: list[str] = []
        listener = lambda _connection, _cursor, statement, *_args: statements.append(statement)
        event.listen(engine, "before_cursor_execute", listener)
        page = ChatRequestService(session).page(page=1)
        event.remove(engine, "before_cursor_execute", listener)

        assert len(page.records) == 50 and page.total == 1000 and page.has_next is True
        assert len(statements) == 2
        assert page.records[0].request_key == "scale-request-1000"
        assert page.records[0].recovered_from_request_key == "scale-request-0001"


def test_operational_history_pages_navigate_without_inventory_mutation(
    history_store,
) -> None:
    factory, app, _ = history_store
    with factory() as session:
        events_before = int(session.scalar(select(func.count(Event.id))) or 0)

    with TestClient(app) as client:
        conversation = client.get("/api/conversations/1")
        older = client.get(
            f"/api/conversations/1?before_id={conversation.json()['next_before_id']}"
        )
        evaluations = client.get("/evaluations?page=1&page_size=50")
        experiments = client.get("/experiments?page=1&page_size=50")
        requests = client.get("/chat-requests?page=1&page_size=50")

    assert len(conversation.json()["messages"]) == 50
    assert len(older.json()["messages"]) == 50
    assert conversation.json()["has_older"] is True
    assert "Next" in evaluations.text
    assert "Next" in experiments.text
    assert "Next" in requests.text

    with factory() as session:
        assert int(session.scalar(select(func.count(Event.id))) or 0) == events_before == 0
