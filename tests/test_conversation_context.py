# test_conversation_context.py
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient
from ah_there_it_is.db.models import AgentRunLog, Message
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService


@contextmanager
def _observe_messages(session: Session):
    loaded: list[Message] = []
    statements: list[str] = []

    def on_load(_session, instance) -> None:
        if isinstance(instance, Message):
            loaded.append(instance)

    def on_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement)

    engine = session.get_bind()
    event.listen(session, "loaded_as_persistent", on_load)
    event.listen(engine, "before_cursor_execute", on_statement)
    try:
        yield loaded, statements
    finally:
        event.remove(session, "loaded_as_persistent", on_load)
        event.remove(engine, "before_cursor_execute", on_statement)

def _seed_messages(session: Session, count: int) -> int:
    conversation = ConversationService(session).create()
    started = datetime(2020, 1, 1, tzinfo=timezone.utc)
    if count:
        session.execute(
            Message.__table__.insert(),
            [
                {
                    "conversation_id": conversation.id,
                    "role": "user" if index % 2 else "assistant",
                    "content": f"persisted-{index:04d}",
                    "created_at": started + timedelta(seconds=index),
                }
                for index in range(1, count + 1)
            ],
        )
        session.commit()
    session.expunge_all()
    return conversation.id


def test_agent_context_window_rules_and_new_conversation(session: Session) -> None:
    conversations = ConversationService(session)
    empty_id = conversations.create().id
    assert conversations.list_agent_context_messages(empty_id) == []

    fresh_llm = ScriptedLLMClient([LLMResponse(content="Fresh reply.")])
    fresh = AgentRunner(session, fresh_llm).run("First turn")

    assert [message.role for message in fresh_llm.calls[0][0]] == [
        "system", "user",
    ]
    assert fresh_llm.calls[0][0][-1].content == "First turn"
    assert len(ConversationService(session).list_messages(fresh.conversation_id)) == 2

    short_id = _seed_messages(session, 3)
    short = ConversationService(session).list_agent_context_messages(short_id)
    assert [message.content for message in short] == [
        "persisted-0001", "persisted-0002", "persisted-0003",
    ]

    exact_id = _seed_messages(session, 40)
    exact = ConversationService(session).list_agent_context_messages(exact_id)
    assert len(exact) == 40
    assert exact[0].role == "user"
    assert [message.content for message in exact] == [
        f"persisted-{index:04d}" for index in range(1, 41)
    ]

    over_id = _seed_messages(session, 41)
    over = ConversationService(session).list_agent_context_messages(over_id)
    assert len(over) == 39
    assert over[0].role == "user"
    assert over[0].content == "persisted-0003"
    assert over[-1].content == "persisted-0041"
    assert "persisted-0001" not in {message.content for message in over}


def test_agent_run_loads_only_40_of_1000_and_logs_sent_context(
    session: Session,
) -> None:
    conversation_id = _seed_messages(session, 1000)
    llm = ScriptedLLMClient([LLMResponse(content="Bounded reply.")])

    with _observe_messages(session) as (loaded, statements):
        result = AgentRunner(session, llm).run(
            " current turn ",
            conversation_id=conversation_id,
        )

    assert len(loaded) <= ConversationService.AGENT_CONTEXT_MESSAGE_LIMIT
    assert any(
        "FROM MESSAGES" in statement.upper() and "LIMIT" in statement.upper()
        for statement in statements
    )
    sent = llm.calls[0][0]
    assert len(sent) == 42
    assert sent[0].role == "system"
    assert [message.content for message in sent[1:41]] == [
        f"persisted-{index:04d}" for index in range(961, 1001)
    ]

    assert sent[-1].role == "user" and sent[-1].content == "current turn"
    assert all(message.content != "persisted-0960" for message in sent)
    run = EvaluationService(session).get_run(result.run_id)
    assert run.input_messages == [
        message.model_dump(mode="json") for message in sent
    ]

    stored = ConversationService(session).list_messages(conversation_id)
    assert len(stored) == 1002
    assert stored[0].content == "persisted-0001"
    assert [message.content for message in stored[-2:]] == [
        "current turn", "Bounded reply.",
    ]
    assert session.scalar(
        select(func.count(AgentRunLog.id)).where(
            AgentRunLog.conversation_id == conversation_id
        )
    ) == 1
