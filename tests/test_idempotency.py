from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.runner import AgentRunner
from ah_there_it_is.db.models import ChatRequestRecord, Event, Item, Message
from ah_there_it_is.services.chat_requests import (
    ChatRequestService,
    IdempotencyConflictError,
    IdempotencyInProgressError,
    ChatRequestNotFoundError,
    IdempotencyPreviousFailureError,
    IdempotencyRecoveryNotAllowedError,
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
        operation=lambda commit: AgentRunner(session, llm).run("Create USB tester", commit_on_success=commit),
    )
    after_first = event_count(session)
    messages_after_first = message_count(session)

    second = service.execute(
        request_key="create-retry-0001",
        message="Create USB tester",
        conversation_id=None,
        operation=lambda commit: (_ for _ in ()).throw(
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
        operation=lambda commit: AgentRunner(session, llm).run("Move CH341A", commit_on_success=commit),
    )
    after_first = event_count(session)
    second = service.execute(
        request_key="move-retry-0001",
        message="Move CH341A",
        conversation_id=None,
        operation=lambda commit: (_ for _ in ()).throw(
            AssertionError("operation must not be invoked on replay")
        ),
    )

    assert second.result.run_id == first.result.run_id
    assert inventory.get_item(item.id).current_location_id == drawer.id
    assert after_first == before + 1
    assert event_count(session) == after_first


def test_partial_split_retry_does_not_create_another_child(session: Session) -> None:
    inventory = InventoryService(session)
    source = inventory.create_item("Bolts", quantity=10)
    drawer = inventory.create_location("Middle drawer")
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="Bolts"),)),
        LLMResponse(tool_calls=(call("2", "search_locations", query="Middle drawer"),)),
        LLMResponse(tool_calls=(call(
            "3", "move_item", item_id=source.id, location_id=drawer.id,
            portion={"mode": "exact", "value": 3},
        ),)),
        LLMResponse(content="Moved."),
    ])
    service = ChatRequestService(session)
    first = service.execute(
        request_key="partial-split-retry-0069",
        message="Move three Bolts",
        conversation_id=None,
        operation=lambda commit: AgentRunner(session, llm).run(
            "Move three Bolts", commit_on_success=commit
        ),
    )
    after_items = session.scalar(select(func.count()).select_from(Item))
    after_events = event_count(session)
    replay = service.execute(
        request_key="partial-split-retry-0069",
        message="Move three Bolts",
        conversation_id=None,
        operation=lambda commit: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert replay.replayed is True and replay.result == first.result
    assert session.scalar(select(func.count()).select_from(Item)) == after_items == 2
    assert event_count(session) == after_events


def test_removed_retry_does_not_duplicate_event(session: Session) -> None:
    inventory = InventoryService(session)
    item = inventory.create_item("Cable")
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="Cable"),)),
        LLMResponse(tool_calls=(call(
            "2", "remove_item", item_id=item.id,
            reason="given away", reason_source="explicit",
        ),)),
        LLMResponse(content="Removed."),
    ])
    service = ChatRequestService(session)
    first = service.execute(
        request_key="removed-retry-0069",
        message="Give Cable away",
        conversation_id=None,
        operation=lambda commit: AgentRunner(session, llm).run(
            "Give Cable away", commit_on_success=commit
        ),
    )
    after_events = event_count(session)
    replay = service.execute(
        request_key="removed-retry-0069",
        message="Give Cable away",
        conversation_id=None,
        operation=lambda commit: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert replay.replayed is True and replay.result == first.result
    assert inventory.get_item(item.id).state == "removed"
    assert event_count(session) == after_events


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
        operation=lambda commit: AgentRunner(session, llm).run(
            "DT-830B has broken probes", commit_on_success=commit
        ),
    )
    after_first = event_count(session)
    second = service.execute(
        request_key="update-retry-0001",
        message="DT-830B has broken probes",
        conversation_id=None,
        operation=lambda commit: (_ for _ in ()).throw(
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
                operation=lambda commit: AgentRunner(
                    first_session,
                    ScriptedLLMClient([LLMResponse(content="Stored answer")]),
                ).run("Where is it?", commit_on_success=commit),
            )

        with factory() as second_session:
            replay = ChatRequestService(second_session).execute(
                request_key="persistent-key-0001",
                message="Where is it?",
                conversation_id=None,
                operation=lambda commit: (_ for _ in ()).throw(
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
        operation=lambda commit: AgentRunner(
            session, ScriptedLLMClient([LLMResponse(content="ok")])
        ).run("one", commit_on_success=commit),
    )

    with pytest.raises(IdempotencyConflictError):
        service.execute(
            request_key="conflict-key-0001",
            message="two",
            conversation_id=None,
            operation=lambda commit: (_ for _ in ()).throw(
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
            operation=lambda commit: (_ for _ in ()).throw(
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
            operation=lambda commit: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    record = service.get("failed-key-0001")
    assert record is not None
    assert record.status == "failed"

    with pytest.raises(IdempotencyPreviousFailureError):
        service.execute(
            request_key="failed-key-0001",
            message="same",
            conversation_id=None,
            operation=lambda commit: (_ for _ in ()).throw(
                AssertionError("failed request must not restart")
            ),
        )


def test_failed_request_can_be_recovered_as_new_audited_attempt(session: Session) -> None:
    service = ChatRequestService(session)
    with pytest.raises(RuntimeError, match="boom"):
        service.execute(
            request_key="failed-source-0001",
            message="Where is CH341A?",
            conversation_id=None,
            operation=lambda commit: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    recovered = service.recover(
        source_request_key="failed-source-0001",
        new_request_key="recovery-attempt-0001",
        recovery_note="Operator verified the failed turn rolled back.",
        operation=lambda commit: AgentRunner(
            session,
            ScriptedLLMClient([LLMResponse(content="Recovered answer")]),
        ).run("Where is CH341A?", commit_on_success=commit),
    )

    source = service.get("failed-source-0001")
    attempt = service.get("recovery-attempt-0001")
    assert recovered.replayed is False
    assert source is not None and source.status == "failed"
    assert attempt is not None and attempt.status == "completed"
    assert attempt.recovered_from_id == source.id
    assert attempt.recovery_note == "Operator verified the failed turn rolled back."
    assert attempt.request_key != source.request_key


def test_recovery_retry_replays_same_new_attempt_without_second_operation(
    session: Session,
) -> None:
    service = ChatRequestService(session)
    session.add(
        ChatRequestRecord(
            request_key="processing-source-0001",
            requested_conversation_id=None,
            message="same",
            status="processing",
        )
    )
    session.commit()

    first = service.recover(
        source_request_key="processing-source-0001",
        new_request_key="manual-recovery-0001",
        recovery_note="Operator accepts duplicate-risk after inspection.",
        operation=lambda commit: AgentRunner(
            session,
            ScriptedLLMClient([LLMResponse(content="Recovered")]),
        ).run("same", commit_on_success=commit),
    )
    second = service.recover(
        source_request_key="processing-source-0001",
        new_request_key="manual-recovery-0001",
        recovery_note="Operator accepts duplicate-risk after inspection.",
        operation=lambda commit: (_ for _ in ()).throw(
            AssertionError("recovery replay must not execute twice")
        ),
    )

    assert second.replayed is True
    assert second.result == first.result


def test_completed_request_cannot_be_recovered(session: Session) -> None:
    service = ChatRequestService(session)
    service.execute(
        request_key="completed-source-0001",
        message="done",
        conversation_id=None,
        operation=lambda commit: AgentRunner(
            session,
            ScriptedLLMClient([LLMResponse(content="Done")]),
        ).run("done", commit_on_success=commit),
    )

    with pytest.raises(IdempotencyRecoveryNotAllowedError, match="must be replayed"):
        service.recover(
            source_request_key="completed-source-0001",
            new_request_key="should-not-run-0001",
            recovery_note="Not needed.",
            operation=lambda commit: (_ for _ in ()).throw(
                AssertionError("completed source must not recover")
            ),
        )


def test_recovery_requires_existing_source_and_audit_note(session: Session) -> None:
    service = ChatRequestService(session)
    with pytest.raises(ChatRequestNotFoundError):
        service.recover(
            source_request_key="missing-source-0001",
            new_request_key="recovery-0002",
            recovery_note="operator note",
            operation=lambda commit: (_ for _ in ()).throw(AssertionError()),
        )

    session.add(
        ChatRequestRecord(
            request_key="failed-source-0002",
            requested_conversation_id=None,
            message="same",
            status="failed",
            error="boom",
        )
    )
    session.commit()

    with pytest.raises(IdempotencyRecoveryNotAllowedError, match="recovery note"):
        service.recover(
            source_request_key="failed-source-0002",
            new_request_key="recovery-0003",
            recovery_note="   ",
            operation=lambda commit: (_ for _ in ()).throw(AssertionError()),
        )


def test_recent_requests_orders_latest_update_first(session: Session) -> None:
    service = ChatRequestService(session)
    first = ChatRequestRecord(
        request_key="recent-0001",
        requested_conversation_id=None,
        message="one",
        status="processing",
    )
    second = ChatRequestRecord(
        request_key="recent-0002",
        requested_conversation_id=None,
        message="two",
        status="failed",
        error="x",
    )
    session.add_all([first, second])
    session.commit()

    rows = service.recent(limit=2)
    assert [row.request_key for row in rows] == ["recent-0002", "recent-0001"]


def test_request_projection_pages_recovery_links_without_n_plus_one(
    session: Session,
) -> None:
    source = ChatRequestRecord(
        request_key="projection-source",
        requested_conversation_id=None,
        message="source",
        status="failed",
        error="failed",
    )
    session.add(source)
    session.flush()
    session.add_all(
        ChatRequestRecord(
            request_key=f"projection-{index:04d}",
            requested_conversation_id=None,
            message="retry",
            status="failed",
            error="failed",
            recovered_from_id=source.id,
            recovery_note="checked",
        )
        for index in range(1005)
    )
    session.commit()
    session.expunge_all()

    statements: list[str] = []
    engine = session.get_bind()
    event.listen(
        engine,
        "before_cursor_execute",
        lambda _connection, _cursor, statement, *_args: statements.append(statement),
    )
    service = ChatRequestService(session)
    first = service.page(page=1, page_size=100)
    second = service.page(page=2, page_size=100)
    api_rows = service.recent_projection(limit=500)

    assert len(first.records) == len(second.records) == 100
    assert first.total == 1006 and first.has_next is True
    assert first.records[0].id > first.records[-1].id > second.records[-1].id
    assert all(row.recovered_from_request_key == "projection-source" for row in first.records)
    assert len(api_rows) == 500
    assert len(statements) == 5
    for page, page_size in ((0, 50), (1, 0), (1, 101)):
        with pytest.raises(ValueError):
            service.page(page=page, page_size=page_size)


def test_concurrent_same_key_allows_exactly_one_operation(tmp_path) -> None:
    from ah_there_it_is.db.models import AgentRunLog, Base
    from ah_there_it_is.db.search_schema import install_fts_schema
    from ah_there_it_is.db.session import create_db_engine, create_session_factory

    database = tmp_path / "concurrent-idempotency.db"
    engine = create_db_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    factory = create_session_factory(engine)

    barrier = threading.Barrier(2)
    operation_calls = 0
    operation_lock = threading.Lock()
    outcomes: list[str] = []

    def worker() -> None:
        nonlocal operation_calls
        with factory() as worker_session:
            barrier.wait()

            def operation(commit: bool):
                nonlocal operation_calls
                with operation_lock:
                    operation_calls += 1
                time.sleep(0.15)
                return AgentRunner(
                    worker_session,
                    ScriptedLLMClient([LLMResponse(content="once")]),
                ).run("same", commit_on_success=commit)

            try:
                ChatRequestService(worker_session).execute(
                    request_key="concurrent-key-0001",
                    message="same",
                    conversation_id=None,
                    operation=operation,
                )
                outcomes.append("completed")
            except IdempotencyInProgressError:
                outcomes.append("processing")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert sorted(outcomes) == ["completed", "processing"]
        assert operation_calls == 1

        with factory() as check_session:
            records = list(check_session.scalars(select(ChatRequestRecord)))
            runs = list(check_session.scalars(select(AgentRunLog)))
            assert len(records) == 1
            assert records[0].status == "completed"
            assert len(runs) == 1
    finally:
        engine.dispose()
