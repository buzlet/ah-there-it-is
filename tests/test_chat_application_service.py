from __future__ import annotations

import pytest

from ah_there_it_is.agent import LLMResponse, ScriptedLLMClient, ToolCall
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
