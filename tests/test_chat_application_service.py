from __future__ import annotations

import pytest
from sqlalchemy import func, select

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
from ah_there_it_is.agent.errors import AgentTurnFailedError
from ah_there_it_is.db.models import AgentRunLog, ChatRequestRecord, Conversation, Message
from ah_there_it_is.services.chat_application import ChatApplicationService
from ah_there_it_is.services.chat_requests import ChatRequestService


def test_shared_chat_service_persists_source_identity_and_replays_without_overwrite(
    session,
) -> None:
    llm = ScriptedLLMClient(
        [
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="1",
                        name="search_items",
                        arguments={"query": "Shared item"},
                    ),
                )
            ),
            LLMResponse(
                tool_calls=(
                    ToolCall(
                        id="2",
                        name="create_item",
                        arguments={"name": "Shared item"},
                    ),
                )
            ),
            LLMResponse(content="Created."),
        ]
    )
    service = ChatApplicationService(session, lambda: llm)

    first = service.execute_chat(
        "Create Shared item",
        request_key="shared-chat-0074",
        source_identity=" telegram:42 ",
    )
    replay = service.execute_chat(
        "Create Shared item",
        request_key="shared-chat-0074",
        source_identity="web",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.result == first.result
    record = ChatRequestService(session).get("shared-chat-0074")
    assert record is not None
    assert record.source_identity == "telegram:42"
    assert llm.remaining == 0


def test_shared_chat_service_rejects_blank_source_identity(session) -> None:
    service = ChatApplicationService(session, lambda: ScriptedLLMClient([]))
    with pytest.raises(ValueError, match="source_identity"):
        service.execute_chat(
            "No-op",
            request_key="shared-chat-blank-0074",
            source_identity="  ",
        )


def test_failed_first_keyed_turn_keeps_only_audit_anchor_and_failure_evidence(
    session,
) -> None:
    service = ChatApplicationService(
        session,
        lambda: ScriptedLLMClient(
            [
                LLMResponse(
                    tool_calls=(
                        ToolCall(
                            id="1",
                            name="create_item",
                            arguments={"name": "Unsearched"},
                        ),
                    )
                )
            ]
        ),
    )

    with pytest.raises(AgentTurnFailedError):
        service.execute_chat(
            "Create Unsearched",
            request_key="failed-first-0084",
            source_identity="web",
        )

    conversations = list(session.scalars(select(Conversation)))
    messages = list(session.scalars(select(Message)))
    runs = list(session.scalars(select(AgentRunLog)))
    requests = list(session.scalars(select(ChatRequestRecord)))

    assert len(conversations) == 1
    assert messages == []
    assert len(runs) == 1
    assert runs[0].conversation_id == conversations[0].id
    assert runs[0].status == "failed"
    assert runs[0].user_message_id is None
    assert runs[0].assistant_message_id is None
    assert runs[0].mutation_receipts == []
    assert len(requests) == 1
    assert requests[0].request_key == "failed-first-0084"
    assert requests[0].status == "failed"
    assert requests[0].agent_run_id is None
    assert requests[0].requested_conversation_id is None
    assert session.scalar(select(func.count()).select_from(Message)) == 0
