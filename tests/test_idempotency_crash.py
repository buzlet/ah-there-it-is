# test_idempotency_crash.py
"""Fault injection around keyed chat final commits."""

from __future__ import annotations

import sqlite3
import threading

import pytest
from sqlalchemy import func, select

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.db.models import AgentRunLog, Base, ChatRequestRecord, Event, Item, Message
from ah_there_it_is.db.search_schema import install_fts_schema
from ah_there_it_is.db.session import create_db_engine, create_session_factory
from ah_there_it_is.services.chat_requests import (
    ChatRequestService, IdempotencyError, IdempotencyInProgressError,
)
from ah_there_it_is.services.inventory import InventoryService


def call(call_id: str, tool_name: str, **arguments) -> ToolCall:
    return ToolCall(id=call_id, name=tool_name, arguments=arguments)


@pytest.fixture
def database_factory(tmp_path):
    path = tmp_path / "requests.db"
    engine = create_db_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_fts_schema(connection)
    try:
        yield path, create_session_factory(engine)
    finally:
        engine.dispose()


def create_llm() -> ScriptedLLMClient:
    return ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="New meter"),)),
        LLMResponse(tool_calls=(call("2", "create_item", name="New meter"),)),
        LLMResponse(content="Done."),
    ])


def run_keyed(session, key: str, llm=None):
    llm = llm or create_llm()
    return ChatRequestService(session).execute(
        request_key=key,
        message="Create New meter",
        conversation_id=None,
        operation=lambda commit: AgentRunner(session, llm).run(
            "Create New meter", commit_on_success=commit
        ),
    )


def counts(session) -> tuple[int, int, int, int]:
    return tuple(int(session.scalar(select(func.count(model.id))) or 0)
                 for model in (Item, Event, Message, AgentRunLog))


def test_final_commit_failure_before_commit_rolls_back_and_marks_failed(database_factory) -> None:
    _, factory = database_factory
    with factory() as session:
        service = ChatRequestService(session)
        def fail_before_commit() -> None:
            raise RuntimeError("injected before commit")
        service._commit_completed = fail_before_commit
        with pytest.raises(RuntimeError, match="injected before commit"):
            service.execute(
                request_key="before-commit-0015", message="Create New meter",
                conversation_id=None,
                operation=lambda commit: AgentRunner(session, create_llm()).run(
                    "Create New meter", commit_on_success=commit
                ),
            )
    with factory() as durable:
        record = ChatRequestService(durable).get("before-commit-0015")
        assert record is not None and record.status == "failed"
        assert "final commit failure" in (record.error or "")
        assert record.agent_run_id is None
        assert counts(durable) == (0, 0, 0, 0)


def test_commit_exception_after_durable_commit_reconciles_completed(database_factory) -> None:
    _, factory = database_factory
    with factory() as session:
        service = ChatRequestService(session)
        def raise_after_commit() -> None:
            session.commit()
            raise RuntimeError("response from commit was lost")
        service._commit_completed = raise_after_commit
        result = service.execute(
            request_key="after-commit-0015", message="Create New meter",
            conversation_id=None,
            operation=lambda commit: AgentRunner(session, create_llm()).run(
                "Create New meter", commit_on_success=commit
            ),
        )
        assert result.replayed is True
        assert result.result.changes_applied is True
        assert len(result.result.receipts) == 1
    with factory() as durable:
        record = ChatRequestService(durable).get("after-commit-0015")
        assert record is not None and record.status == "completed"
        assert record.agent_run_id == result.result.run_id
        assert counts(durable) == (1, 1, 2, 1)


def test_response_loss_after_successful_commit_replays_without_new_mutation(database_factory) -> None:
    _, factory = database_factory
    with factory() as session:
        first = run_keyed(session, "response-loss-0015")
        assert first.replayed is False
        # Model the caller losing the response after execute returned.
        try:
            raise ConnectionError("HTTP response lost")
        except ConnectionError:
            pass
    with factory() as session:
        replay = ChatRequestService(session).execute(
            request_key="response-loss-0015", message="Create New meter",
            conversation_id=None,
            operation=lambda commit: (_ for _ in ()).throw(AssertionError("must not execute")),
        )
        assert replay.replayed is True
        assert replay.result == first.result
        assert counts(session) == (1, 1, 2, 1)


def test_inconsistent_durable_state_is_preserved_and_rejected(database_factory) -> None:
    _, factory = database_factory
    with factory() as session:
        service = ChatRequestService(session)
        def inconsistent_commit() -> None:
            session.rollback()
            with factory() as external:
                record = ChatRequestService(external).get("inconsistent-0015")
                assert record is not None
                record.status = "completed"
                external.commit()
            raise RuntimeError("uncertain")
        service._commit_completed = inconsistent_commit
        with pytest.raises(IdempotencyError, match="invalid stored state"):
            service.execute(
                request_key="inconsistent-0015", message="Create New meter",
                conversation_id=None,
                operation=lambda commit: AgentRunner(session, create_llm()).run(
                    "Create New meter", commit_on_success=commit
                ),
            )
    with factory() as durable:
        record = ChatRequestService(durable).get("inconsistent-0015")
        assert record is not None and record.status == "completed"
        assert record.agent_run_id is None
        assert counts(durable) == (0, 0, 0, 0)


def test_concurrent_same_key_cannot_execute_two_mutations(database_factory) -> None:
    _, factory = database_factory
    reserved = threading.Event()
    release = threading.Event()
    outcomes: list[object] = []

    def first_request() -> None:
        with factory() as session:
            def operation(commit: bool):
                reserved.set()
                assert release.wait(timeout=5)
                return AgentRunner(session, create_llm()).run(
                    "Create New meter", commit_on_success=commit
                )
            outcomes.append(ChatRequestService(session).execute(
                request_key="concurrent-mutation-0015", message="Create New meter",
                conversation_id=None, operation=operation,
            ))

    thread = threading.Thread(target=first_request)
    thread.start()
    try:
        assert reserved.wait(timeout=5)
        with factory() as second:
            with pytest.raises(IdempotencyInProgressError):
                ChatRequestService(second).execute(
                    request_key="concurrent-mutation-0015", message="Create New meter",
                    conversation_id=None,
                    operation=lambda commit: (_ for _ in ()).throw(AssertionError("must not execute")),
                )
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(outcomes) == 1
    with factory() as durable:
        assert counts(durable) == (1, 1, 2, 1)


def test_quantity_second_writer_is_blocked_after_model_turn_first_flushed_write(database_factory) -> None:
    path, factory = database_factory
    with factory() as setup:
        item = InventoryService(setup).create_item("Meter")
    paused = threading.Event()
    release = threading.Event()
    outcomes: list[object] = []

    class PausingLLM(ScriptedLLMClient):
        def complete(self, messages, tools):
            if len(self.calls) == 2:
                paused.set()
                assert release.wait(timeout=5)
            return super().complete(messages, tools)

    llm = PausingLLM([
        LLMResponse(tool_calls=(call("1", "search_items", query="Meter"),)),
        LLMResponse(tool_calls=(call(
            "2", "change_item_quantity", item_id=item.id,
            quantity_mode="exact", quantity=2,
            reason="recount", reason_source="explicit",
        ),)),
        LLMResponse(content="Done."),
    ])
    def keyed_turn() -> None:
        with factory() as session:
            outcomes.append(ChatRequestService(session).execute(
                request_key="lock-probe-0015", message="Update Meter",
                conversation_id=None,
                operation=lambda commit: AgentRunner(session, llm).run(
                    "Update Meter", commit_on_success=commit
                ),
            ))
    thread = threading.Thread(target=keyed_turn)
    thread.start()
    try:
        assert paused.wait(timeout=5)
        with sqlite3.connect(path, timeout=0.05) as other:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("UPDATE items SET quantity = 3 WHERE id = ?", (item.id,))
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert len(outcomes) == 1
    with factory() as durable:
        assert InventoryService(durable).get_item(item.id).quantity == 2
