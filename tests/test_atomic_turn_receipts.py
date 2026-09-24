# test_atomic_turn_receipts.py
"""Committed receipts and immediate failure semantics for agent turns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import AgentTurnFailedError
from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.db.models import Event
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.inventory import InventoryService


def call(call_id: str, tool_name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=tool_name, arguments=arguments)


def events(session: Session) -> int:
    return int(session.scalar(select(func.count(Event.id))) or 0)


def create_steps(*tail: LLMResponse) -> ScriptedLLMClient:
    return ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="New meter"),)),
        LLMResponse(tool_calls=(call("2", "create_item", name="New meter"),)),
        *tail,
    ])


@pytest.mark.parametrize("failing_call", [
    call("3", "search_items", query="bad", limit=0),
    call("3", "update_item", item_id=999, quantity=2),
])
def test_error_after_changed_mutation_rolls_back_and_stops(
    session: Session, failing_call: ToolCall,
) -> None:
    llm = create_steps(
        LLMResponse(tool_calls=(failing_call,)),
        LLMResponse(content="A later repair must not run."),
    )
    with pytest.raises(AgentTurnFailedError):
        AgentRunner(session, llm).run("Create New meter")

    assert llm.remaining == 1
    from ah_there_it_is.db.models import Item
    assert session.scalar(select(func.count(Item.id))) == 0
    assert events(session) == 0
    run = EvaluationService(session).recent_runs()[0]
    assert run.status == "failed"
    assert run.mutation_receipts == []
    assert run.user_message_id is None
    assert ConversationService(session).list_messages(run.conversation_id) == []
    created = run.tool_trace[1]["tool_results"][0]["result"]
    assert created["changed"] is True
    assert created["commit_state"] == "rolled_back"


def test_mutation_error_before_any_change_fails_without_next_round(session: Session) -> None:
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "create_item", name="Unsearched"),)),
        LLMResponse(content="Repair must not run."),
    ])
    with pytest.raises(AgentTurnFailedError):
        AgentRunner(session, llm).run("Create Unsearched")
    assert llm.remaining == 1
    assert events(session) == 0


def test_read_error_before_mutation_can_be_corrected(session: Session) -> None:
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="x", limit=0),)),
        LLMResponse(tool_calls=(call("2", "search_items", query="New meter"),)),
        LLMResponse(tool_calls=(call("3", "create_item", name="New meter"),)),
        LLMResponse(content="Done."),
    ])
    result = AgentRunner(session, llm).run("Create New meter")
    assert result.changes_applied is True
    assert result.receipts[0].operation == "create_item"
    assert result.receipts[0].changed is True
    assert len(result.receipts[0].event_ids) == 1


def test_empty_final_after_mutation_rolls_back(session: Session) -> None:
    llm = create_steps(LLMResponse(content="  "))
    with pytest.raises(AgentTurnFailedError, match="empty final"):
        AgentRunner(session, llm).run("Create New meter")
    from ah_there_it_is.db.models import Item
    assert session.scalar(select(func.count(Item.id))) == 0
    assert events(session) == 0
    assert EvaluationService(session).recent_runs()[0].mutation_receipts == []


def test_noop_update_and_move_have_false_receipts_without_events(session: Session) -> None:
    inventory = InventoryService(session)
    desk = inventory.create_location("Desk")
    item = inventory.create_item("Meter", location_id=desk.id, quantity=2)
    before = events(session)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="Meter"),)),
        LLMResponse(tool_calls=(call("2", "search_locations", query="Desk"),)),
        LLMResponse(tool_calls=(call("3", "update_item", item_id=item.id, quantity=2),)),
        LLMResponse(tool_calls=(call("4", "move_item", item_id=item.id, location_id=desk.id),)),
        LLMResponse(content="Already correct."),
    ])
    result = AgentRunner(session, llm).run("Check Meter")
    assert result.changes_applied is False
    assert [(receipt.operation, receipt.changed, receipt.event_ids) for receipt in result.receipts] == [
        ("update_item", False, ()), ("move_item", False, ())
    ]
    assert result.receipts[1].before_ids == {"location_id": desk.id}
    assert result.receipts[1].after_ids == {"location_id": desk.id}
    assert events(session) == before
    assert EvaluationService(session).get_run(result.run_id).mutation_receipts[0]["changed"] is False



def test_explicit_take_transition_receipts_track_event_and_noop(session: Session) -> None:
    inventory = InventoryService(session)
    desk = inventory.create_location("Desk")
    item = inventory.create_item("Meter", location_id=desk.id)
    dispatcher = ToolDispatcher(session, autocommit=False)
    args = SimpleNamespace(item_id=item.id)

    before = dispatcher._mutation_before("take_item", args)
    taken = dispatcher.inventory.take_item(item.id)
    receipt = dispatcher._mutation_receipt(
        "take_item", args, dispatcher._item_dict(taken), before
    )
    assert receipt.operation == "take_item"
    assert receipt.changed is True
    assert receipt.before_ids == {"location_id": desk.id}
    assert receipt.after_ids == {"location_id": None}
    assert len(receipt.event_ids) == 1

    before_noop = dispatcher._mutation_before("take_item", args)
    already_taken = dispatcher.inventory.take_item(item.id)
    noop_receipt = dispatcher._mutation_receipt(
        "take_item", args, dispatcher._item_dict(already_taken), before_noop
    )
    assert noop_receipt.changed is False
    assert noop_receipt.event_ids == ()
    assert noop_receipt.before_ids == {"location_id": None}
    assert noop_receipt.after_ids == {"location_id": None}



def test_all_explicit_transition_operations_have_location_receipts(session: Session) -> None:
    inventory = InventoryService(session)
    desk = inventory.create_location("Desk")
    item = inventory.create_item("Meter", location_id=desk.id)
    dispatcher = ToolDispatcher(session, autocommit=False)
    args = SimpleNamespace(item_id=item.id)

    def apply(operation: str, mutate):
        before = dispatcher._mutation_before(operation, args)
        changed_item = mutate()
        return dispatcher._mutation_receipt(
            operation, args, dispatcher._item_dict(changed_item), before
        )

    taken = apply("take_item", lambda: dispatcher.inventory.take_item(item.id))
    assert taken.changed is True and taken.event_ids
    assert taken.before_ids == {"location_id": desk.id}
    assert taken.after_ids == {"location_id": None}

    unknown = apply(
        "mark_item_location_unknown",
        lambda: dispatcher.inventory.mark_item_location_unknown(item.id),
    )
    assert unknown.changed is True and unknown.event_ids
    assert unknown.before_ids == {"location_id": None}
    assert unknown.after_ids == {"location_id": None}

    discarded = apply("discard_item", lambda: dispatcher.inventory.discard_item(item.id))
    assert discarded.changed is True and discarded.event_ids
    assert discarded.before_ids == {"location_id": None}
    assert discarded.after_ids == {"location_id": None}
    discard_noop = apply("discard_item", lambda: dispatcher.inventory.discard_item(item.id))
    assert discard_noop.changed is False and discard_noop.event_ids == ()

    reactivated_unknown = apply(
        "reactivate_item",
        lambda: dispatcher.inventory.reactivate_item(
            item.id, state="used", location_id=None
        ),
    )
    assert reactivated_unknown.changed is True and reactivated_unknown.event_ids
    assert reactivated_unknown.before_ids == {"location_id": None}
    assert reactivated_unknown.after_ids == {"location_id": None}

    sold = apply("mark_item_sold", lambda: dispatcher.inventory.mark_item_sold(item.id))
    assert sold.changed is True and sold.event_ids
    assert sold.before_ids == {"location_id": None}
    assert sold.after_ids == {"location_id": None}
    sold_noop = apply("mark_item_sold", lambda: dispatcher.inventory.mark_item_sold(item.id))
    assert sold_noop.changed is False and sold_noop.event_ids == ()

    reactivated_known = apply(
        "reactivate_item",
        lambda: dispatcher.inventory.reactivate_item(
            item.id, state="working", location_id=desk.id
        ),
    )
    assert reactivated_known.changed is True and reactivated_known.event_ids
    assert reactivated_known.before_ids == {"location_id": None}
    assert reactivated_known.after_ids == {"location_id": desk.id}


def test_failed_turn_is_absent_from_later_conversation_context(session: Session) -> None:
    first = AgentRunner(session, ScriptedLLMClient([LLMResponse(content="Earlier.")])).run("First")
    failing = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "create_item", name="Unsearched"),)),
    ])
    with pytest.raises(AgentTurnFailedError):
        AgentRunner(session, failing).run("Failed text", conversation_id=first.conversation_id)
    later = ScriptedLLMClient([LLMResponse(content="Later.")])
    AgentRunner(session, later).run("Next", conversation_id=first.conversation_id)
    assert [message.content for message in later.calls[0][0]][1:] == [
        "First", "Earlier.", "Next"
    ]
    run = EvaluationService(session).recent_runs()[1]
    assert run.status == "failed"
    assert run.input_messages[-1]["content"] == "Failed text"


def test_completed_replay_uses_persisted_receipts(session: Session) -> None:
    llm = create_steps(LLMResponse(content="I might have changed something."))
    service = ChatRequestService(session)
    first = service.execute(
        request_key="receipt-replay-0014", message="Create New meter", conversation_id=None,
        operation=lambda commit: AgentRunner(session, llm).run("Create New meter", commit_on_success=commit),
    )
    replay = service.execute(
        request_key="receipt-replay-0014", message="Create New meter", conversation_id=None,
        operation=lambda commit: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    assert replay.replayed is True
    assert replay.result == first.result
    assert replay.result.changes_applied is True
    assert replay.result.receipts[0].event_ids
    assert len(EvaluationService(session).get_run(first.result.run_id).mutation_receipts) == 1


def test_chat_metadata_is_authoritative_despite_assistant_wording() -> None:
    from fastapi.testclient import TestClient
    from tests.test_app import build_test_app

    app, factory, engine = build_test_app()
    llm = create_steps(LLMResponse(content="I did nothing."))
    app.state.llm_factory = lambda: llm
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Create New meter"})
        assert response.status_code == 200
        body = response.json()
        assert body["content"] == "I did nothing."
        assert body["changes_applied"] is True
        assert body["receipts"][0]["operation"] == "create_item"
        with factory() as session:
            assert EvaluationService(session).get_run(body["run_id"]).mutation_receipts == body["receipts"]
    finally:
        engine.dispose()


def test_chat_mutation_error_returns_failure_without_conversation_message() -> None:
    from fastapi.testclient import TestClient
    from tests.test_app import build_test_app

    app, factory, engine = build_test_app()
    app.state.llm_factory = lambda: ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "create_item", name="Unsearched"),)),
    ])
    try:
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"message": "Create Unsearched"})
        assert response.status_code == 409
        with factory() as session:
            run = EvaluationService(session).recent_runs()[0]
            assert run.status == "failed"
            assert run.mutation_receipts == []
            assert ConversationService(session).list_messages(run.conversation_id) == []
    finally:
        engine.dispose()
