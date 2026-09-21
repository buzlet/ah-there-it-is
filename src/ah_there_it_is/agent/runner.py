"""Bounded provider-neutral agent loop."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ah_there_it_is.agent.errors import AgentLoopLimitError
from ah_there_it_is.agent.protocol import AgentMessage, LLMClient
from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.services.conversations import ConversationService


SYSTEM_PROMPT = """You are the text interface to a personal inventory.
Use tools to inspect real inventory data before making claims about it.
Never invent entity IDs. Search first and use only IDs returned by tools.
Before creating an entity, search for the proposed name first.
If multiple candidates remain plausible, ask the user to clarify instead of guessing.
Mutation tools are explicit and ID-based. Tool errors are authoritative; correct your plan.
Keep final user-facing answers concise and distinguish known data from inference.
"""


@dataclass(frozen=True)
class AgentRunResult:
    conversation_id: int
    content: str
    rounds: int


class AgentRunner:
    def __init__(
        self,
        session: Session,
        llm: LLMClient,
        *,
        max_rounds: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.session = session
        self.llm = llm
        self.max_rounds = max_rounds
        self.system_prompt = system_prompt
        self.conversations = ConversationService(session)

    def run(self, user_text: str, *, conversation_id: int | None = None) -> AgentRunResult:
        text = user_text.strip()
        if not text:
            raise ValueError("user_text must not be empty")

        if conversation_id is None:
            conversation_id = self.conversations.create().id
        else:
            self.conversations.get(conversation_id)

        prior = self.conversations.list_messages(conversation_id)
        messages = [AgentMessage(role="system", content=self.system_prompt)]
        messages.extend(
            AgentMessage(role=message.role, content=message.content)  # type: ignore[arg-type]
            for message in prior
        )
        messages.append(AgentMessage(role="user", content=text))
        self.conversations.add_message(conversation_id, "user", text)

        dispatcher = ToolDispatcher(self.session, original_text=text)
        definitions = dispatcher.definitions()

        for round_number in range(1, self.max_rounds + 1):
            response = self.llm.complete(messages, definitions)
            messages.append(
                AgentMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            if not response.tool_calls:
                final = response.content.strip()
                self.conversations.add_message(conversation_id, "assistant", final)
                return AgentRunResult(conversation_id, final, round_number)

            dispatcher.begin_round()
            try:
                for call in response.tool_calls:
                    result = dispatcher.execute(call.name, call.arguments)
                    messages.append(
                        AgentMessage(
                            role="tool",
                            content=dispatcher.as_tool_message_content(result),
                            tool_call_id=call.id,
                            tool_name=call.name,
                        )
                    )
            finally:
                dispatcher.end_round()

        raise AgentLoopLimitError(
            f"agent exceeded max_rounds={self.max_rounds} without a final response"
        )
