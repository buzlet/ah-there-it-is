from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.db.models import ChatRequestRecord, Event, Message
from ah_there_it_is.services.chat_requests import (
    ChatRequestService,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyPreviousFailureError,
)
from ah_there_it_is.services.inventory import InventoryService


def call(call_id: str, tool_name: str, **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=tool_name, arguments=arguments)


def event_count(session: Session) -> int:
    return int(session.scalar(select(func.count(Event.id))) or 0)


def message_count(session: Session) -> int:
    return int(session.scalar(select(func.count(Message.id))) or 0)


def test_create_retry_returns_same_run_without_duplicate_event(session: Session) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(call("1", "search_items", query="USB tester"),)
            ),
            LLMResponse(
                tool_calls=(
                    call("2", "create_item", name="USB tester", state="new"),
                )
            ),
            LLMResponse(content="Created."),
        ]
    )
    service = ChatRequestService(session)

    first = service.execute(
        request_key="create-retry-0001",
        message="Create USB tester",
        conversation_id=None,
        operation=lambda: AgentRunner(session, llm).run("Create USB tester"),
    )
    after_first = event_count(session)
    messages_after_first = message_count(session)

    second = service.execute(
        request_key="create-retry-0001",
        message="Create USB tester",
        conversation_id=None,
        operation=lambda: (_ for _ in ()).throw(
            AssertionError("operation must not be invoked on replay")
        ),
    )

    assert first.replayed is False
    assert second.replayed is True
    assert second.result == first.result
    assert llm.remaining == 0
    assert event_count(session) == after_first == 1
    assert message_count(session) == messages_after_first == 2
    assert InventoryService(session).get_item(1).name == "USB tester"


def test_move_retry_does_not_duplicate_history_event(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("CH341A")
    drawer = inventory.create_location("Middle drawer")
    before = event_count(session)
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="CH341A"),)),
            LLMResponse(
                tool_calls=(
                    call("2", "search_locations", query="Middle drawer"),
                )
            ),
            LLMResponse(
                tool_calls=(
                    call(
                        "3",
                        "move_item",
                        item_id=item.id,
                        location_id=drawer.id,
                    ),
                )
            ),
            LLMResponse(content="Moved."),
        ]
    )
    service = ChatRequestService(session)

    first = service.execute(
        request_key="move-retry-0001",
        message="Move CH341A",
        conversation_id=None,
        operation=lambda: AgentRunner(session, llm).run("Move CH341A"),
    )
    after_first = event_count(session)
    second = service.execute(
        request_key="move-retry-0001",
        message="Move CH341A",
        conversation_id=None,
        operation=lambda: (_ for _ in ()).throw(
            AssertionError("operation must not be invoked on replay")
        ),
    )

    assert second.result.run_id == first.result.run_id
    assert inventory.get_item(item.id).current_location_id == drawer.id
    assert after_first == before + 1
    assert event_count(session) == after_first


def test_update_retry_does_not_duplicate_history_event(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("DT-830B")
    before = event_count(session)
    llm = ScriptedLLMClient(
        [
            LLMResponse(tool_calls=(call("1", "search_items", query="DT-830B"),)),
            LLMResponse(
                tool_calls=(
                    call(
                        "2",
                        "update_item",
                        item_id=item.id,
                        description="Broken probes",
                    ),
                )
            ),
            LLMResponse(content="Updated."),
        ]
    )
    service = ChatRequestService(session)

    first = service.execute(
        request_key="update-retry-0001",
        message="DT-830B has broken probes",
        conversation_id=None,
        operation=lambda: AgentRunner(session, llm).run(
            "DT-830B has broken probes"
        ),
    )
    after_first = event_count(session)
    second = service.execute(
        request_key="update-retry-0001",
        message="DT-830B has broken probes",
        conversation_id=None,
        operation=lambda: (_ for _ in ()).throw(
            AssertionError("operation must not be invoked on replay")
        ),
    )

    assert second.result.run_id == first.result.run_id
    assert inventory.get_item(item.id).description == "Broken probes"
    assert after_first == before + 1
    assert event_count(session) == after_first


def test_completed_replay_is_loaded_from_persistent_database(tmp_path) -> None:
    from ah_there_it_is.db.models import Base
    from ah_there_it_is.db.search_schema import install_fts_schema
    from ah_there_it_is.db.session import (
        create_db_engine,
        create_session_factory,
    )

    database = tmp_path / "idempotency.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)

    try:
        with factory() as first_session:
            first = ChatRequestService(first_session).execute(
                request_key="persistent-key-0001",
                message="Where is it?",
                conversation_id=None,
                operation=lambda: AgentRunner(
                    first_session,
                    ScriptedLLMClient([LLMResponse(content="Stored answer")]),
                ).run("Where is it?"),
            )

        with factory() as second_session:
            replay = ChatRequestService(second_session).execute(
                request_key="persistent-key-0001",
                message="Where is it?",
                conversation_id=None,
                operation=lambda: (_ for _ in ()).throw(
                    AssertionError("persistent replay must not execute")
                ),
            )

        assert replay.replayed is True
        assert replay.result == first.result
        assert replay.result.content == "Stored answer"
    finally:
        engine.dispose()


def test_reusing_key_with_different_payload_is_conflict(session: Session) -> None:
    service = ChatRequestService(session)
    service.execute(
        request_key="conflict-key-0001",
        message="one",
        conversation_id=None,
        operation=lambda: AgentRunner(
            session, ScriptedLLMClient([LLMResponse(content="ok")])
        ).run("one"),
    )

    with pytest.raises(IdempotencyConflictError):
        service.execute(
            request_key="conflict-key-0001",
            message="two",
            conversation_id=None,
            operation=lambda: (_ for _ in ()).throw(
                AssertionError("conflicting request must not execute")
            ),
        )


def test_processing_key_never_starts_second_operation(session: Session) -> None:
    session.add(
        ChatRequestRecord(
            request_key="processing-key-0001",
            requested_conversation_id=None,
            message="same",
            status="processing",
        )
    )
    session.commit()

    with pytest.raises(IdempotencyInProgressError):
        ChatRequestService(session).execute(
            request_key="processing-key-0001",
            message="same",
            conversation_id=None,
            operation=lambda: (_ for _ in ()).throw(
                AssertionError("processing request must not execute")
            ),
        )


def test_failed_key_never_restarts_implicitly(session: Session) -> None:
    service = ChatRequestService(session)
    with pytest.raises(RuntimeError, match="boom"):
        service.execute(
            request_key="failed-key-0001",
            message="same",
            conversation_id=None,
            operation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    record = service.get("failed-key-0001")
    assert record is not None
    assert record.status == "failed"

    with pytest.raises(IdempotencyPreviousFailureError):
        service.execute(
            request_key="failed-key-0001",
            message="same",
            conversation_id=None,
            operation=lambda: (_ for _ in ()).throw(
                AssertionError("failed request must not restart")
            ),
        )
