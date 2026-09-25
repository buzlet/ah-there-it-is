from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.agent import AgentRunner, LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import AgentTurnFailedError
from ah_there_it_is.db.models import Event, Item
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.services.evaluation import EvaluationService
from ah_there_it_is.services.inventory import InventoryService


def call(call_id: str, tool_name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=tool_name, arguments=arguments)


def create_item_turn(session: Session, name: str = "Meter"):
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query=name),)),
        LLMResponse(tool_calls=(call("2", "create_item", name=name),)),
        LLMResponse(content="Created."),
    ])
    return AgentRunner(session, llm).run(f"Create {name}")


def undo_turn(session: Session, conversation_id: int):
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("u", "undo_last_action"),)),
        LLMResponse(content="Undone."),
    ])
    return AgentRunner(session, llm).run(
        "Undo that", conversation_id=conversation_id
    )


def test_undo_item_creation_marks_removed_and_preserves_history(session: Session) -> None:
    created = create_item_turn(session)
    item = session.scalar(select(Item))
    original_event_ids = tuple(session.scalars(select(Event.id).order_by(Event.id)))

    undone = undo_turn(session, created.conversation_id)

    session.refresh(item)
    assert item.state == "removed"
    assert item.removal_reason == "undo: item creation"
    assert tuple(session.scalars(select(Event.id).order_by(Event.id)))[:1] == original_event_ids
    assert session.scalars(select(Event.event_type).order_by(Event.id)).all()[-1] == "item_undo_compensated"
    assert undone.receipts[0].operation == "undo_last_action"
    assert undone.receipts[0].undo_of_run_id == created.run_id


def test_undo_does_not_search_past_immediately_preceding_read_only_turn(
    session: Session,
) -> None:
    created = create_item_turn(session)
    read_only = AgentRunner(
        session, ScriptedLLMClient([LLMResponse(content="No changes.")])
    ).run("Look only", conversation_id=created.conversation_id)
    with pytest.raises(AgentTurnFailedError, match="undo_last_action"):
        undo_turn(session, read_only.conversation_id)
    assert session.scalar(select(Item)).state != "removed"


def test_undo_fails_closed_when_expected_post_state_diverged(session: Session) -> None:
    created = create_item_turn(session)
    item = session.scalar(select(Item))
    InventoryService(session).change_item_quantity(
        item.id,
        quantity_mode="exact",
        quantity=2,
        reason="manual recount",
        reason_source="explicit",
    )
    before_events = tuple(session.scalars(select(Event.id).order_by(Event.id)))
    with pytest.raises(AgentTurnFailedError, match="undo_last_action"):
        undo_turn(session, created.conversation_id)
    session.refresh(item)
    assert item.quantity == 2
    assert tuple(session.scalars(select(Event.id).order_by(Event.id))) == before_events


def test_partial_move_undo_compensates_child_without_merge(session: Session) -> None:
    inventory = InventoryService(session)
    shelf = inventory.create_location("Shelf")
    bin_ = inventory.create_location("Bin")
    source = inventory.create_item("Bolts", location_id=shelf.id, quantity=10)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("1", "search_items", query="Bolts"),)),
        LLMResponse(tool_calls=(call("2", "search_locations", query="Bin"),)),
        LLMResponse(tool_calls=(call(
            "3", "move_item", item_id=source.id, location_id=bin_.id,
            portion={"mode": "exact", "value": 3},
        ),)),
        LLMResponse(content="Moved."),
    ])
    moved = AgentRunner(session, llm).run("Move three Bolts to Bin")
    child = session.scalar(select(Item).where(Item.id != source.id))

    undo_turn(session, moved.conversation_id)

    session.refresh(source)
    session.refresh(child)
    assert source.quantity == 7
    assert child.quantity == 3
    assert source.current_location_id == child.current_location_id == shelf.id
    assert session.scalar(select(Item).where(Item.id == child.id)) is not None


def test_keyed_undo_replay_does_not_compensate_twice(session: Session) -> None:
    created = create_item_turn(session)
    service = ChatRequestService(session)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=(call("u", "undo_last_action"),)),
        LLMResponse(content="Undone."),
    ])
    first = service.execute(
        request_key="undo-replay-0067",
        message="Undo that",
        conversation_id=created.conversation_id,
        operation=lambda commit: AgentRunner(session, llm).run(
            "Undo that", conversation_id=created.conversation_id,
            commit_on_success=commit,
        ),
    )
    event_count = len(session.scalars(select(Event.id)).all())
    replay = service.execute(
        request_key="undo-replay-0067",
        message="Undo that",
        conversation_id=created.conversation_id,
        operation=lambda commit: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    assert replay.replayed is True
    assert replay.result == first.result
    assert len(session.scalars(select(Event.id)).all()) == event_count
    assert EvaluationService(session).get_run(first.result.run_id).mutation_receipts[0][
        "undo_of_run_id"
    ] == created.run_id


def test_undo_is_not_a_redo_target(session: Session) -> None:
    created = create_item_turn(session)
    undone = undo_turn(session, created.conversation_id)
    with pytest.raises(AgentTurnFailedError, match="undo_last_action"):
        undo_turn(session, undone.conversation_id)
