"""Bounded provider-neutral agent loop with replay-oriented run logging."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from sqlalchemy.orm import Session

from ah_there_it_is.agent.errors import AgentLoopLimitError, AgentTurnFailedError
from ah_there_it_is.agent.receipts import MutationReceipt
from ah_there_it_is.agent.protocol import AgentMessage, LLMClient
from ah_there_it_is.agent.tools import ToolDispatcher
from ah_there_it_is.services.conversations import ConversationService
from ah_there_it_is.services.evaluation import EvaluationService


SYSTEM_PROMPT_VERSION = "inventory-v1"
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
    run_id: int
    content: str
    rounds: int
    changes_applied: bool = False
    receipts: tuple[MutationReceipt, ...] = ()


class AgentRunner:
    def __init__(
        self,
        session: Session,
        llm: LLMClient,
        *,
        max_rounds: int = 8,
        system_prompt: str = SYSTEM_PROMPT,
        prompt_version: str = SYSTEM_PROMPT_VERSION,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.session = session
        self.llm = llm
        self.max_rounds = max_rounds
        self.system_prompt = system_prompt
        self.prompt_version = prompt_version
        self.conversations = ConversationService(session)
        self.evaluation = EvaluationService(session)

    def run(
        self, user_text: str, *, conversation_id: int | None = None,
        commit_on_success: bool = True,
    ) -> AgentRunResult:
        text = user_text.strip()
        if not text:
            raise ValueError("user_text must not be empty")

        if conversation_id is None:
            conversation_id = self.conversations.create().id
        else:
            self.conversations.get(conversation_id)

        prior = self.conversations.list_agent_context_messages(conversation_id)
        messages = [AgentMessage(role="system", content=self.system_prompt)]
        messages.extend(
            AgentMessage(role=message.role, content=message.content)  # type: ignore[arg-type]
            for message in prior
        )
        messages.append(AgentMessage(role="user", content=text))

        input_messages = [message.model_dump(mode="json") for message in messages]
        tool_trace: list[dict[str, Any]] = []
        dispatcher = ToolDispatcher(
            self.session,
            original_text=text,
            autocommit=False,
            conversation_id=conversation_id,
        )
        rounds = 0
        changed_seen = False

        try:
            for round_number in range(1, self.max_rounds + 1):
                rounds = round_number
                definitions = dispatcher.definitions()
                response = self.llm.complete(messages, definitions)
                round_trace: dict[str, Any] = {
                    "round": round_number,
                    "available_tools": [tool.name for tool in definitions],
                    "assistant": {
                        "content": response.content,
                        "tool_calls": [
                            call.model_dump(mode="json") for call in response.tool_calls
                        ],
                        "metadata": response.metadata,
                    },
                    "tool_results": [],
                }
                tool_trace.append(round_trace)
                messages.append(
                    AgentMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )
                if not response.tool_calls:
                    final = response.content.strip()
                    if changed_seen and not final:
                        raise AgentTurnFailedError("empty final response after mutation")
                    for prior_round in tool_trace:
                        for tool_result in prior_round["tool_results"]:
                            if tool_result["result"].get("commit_state") == "provisional":
                                tool_result["result"]["commit_state"] = "committed"
                    user_message = self.conversations.add_message(
                        conversation_id, "user", text, commit=False
                    )
                    assistant_message = self.conversations.add_message(
                        conversation_id,
                        "assistant",
                        final,
                        commit=False,
                    )
                    run = self._record_run(
                        conversation_id=conversation_id,
                        user_message_id=user_message.id,
                        assistant_message_id=assistant_message.id,
                        input_messages=input_messages,
                        tool_trace=tool_trace,
                        mutation_receipts=[
                            receipt.model_dump(mode="json") for receipt in dispatcher.receipts
                        ],
                        final_content=final,
                        rounds=round_number,
                        status="completed",
                        commit=False,
                    )
                    if commit_on_success:
                        self.session.commit()
                    return AgentRunResult(
                        conversation_id=conversation_id,
                        run_id=run.id,
                        content=final,
                        rounds=round_number,
                        changes_applied=changed_seen,
                        receipts=tuple(dispatcher.receipts),
                    )

                dispatcher.begin_round()
                try:
                    for call in response.tool_calls:
                        result = dispatcher.execute(call.name, call.arguments)
                        round_trace["tool_results"].append(
                            {
                                "tool_call_id": call.id,
                                "tool_name": call.name,
                                "arguments": call.arguments,
                                "result": result,
                            }
                        )
                        messages.append(
                            AgentMessage(
                                role="tool",
                                content=dispatcher.as_tool_message_content(result),
                                tool_call_id=call.id,
                                tool_name=call.name,
                            )
                        )
                        if not result["ok"] and (
                            changed_seen or call.name in ToolDispatcher.MUTATION_TOOLS
                        ):
                            raise AgentTurnFailedError(
                                f"tool {call.name} failed: {result['error']['type']}"
                            )
                        if result.get("changed") is True:
                            changed_seen = True
                finally:
                    dispatcher.end_round()

            raise AgentLoopLimitError(
                f"agent exceeded max_rounds={self.max_rounds} without a final response"
            )
        except Exception as exc:
            self.session.rollback()
            for round_trace in tool_trace:
                for tool_result in round_trace["tool_results"]:
                    if tool_result["result"].get("commit_state") == "provisional":
                        tool_result["result"]["commit_state"] = "rolled_back"
            self._record_run(
                conversation_id=conversation_id,
                user_message_id=None,
                assistant_message_id=None,
                input_messages=input_messages,
                tool_trace=tool_trace,
                mutation_receipts=[],
                final_content=None,
                rounds=rounds,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    def _record_run(
        self,
        *,
        conversation_id: int,
        user_message_id: int | None,
        assistant_message_id: int | None,
        input_messages: list[dict[str, Any]],
        tool_trace: list[dict[str, Any]],
        mutation_receipts: list[dict[str, Any]],
        final_content: str | None,
        rounds: int,
        status: str,
        error: str | None = None,
        commit: bool = True,
    ):
        info = self.llm.info
        prompt_hash = hashlib.sha256(self.system_prompt.encode("utf-8")).hexdigest()
        return self.evaluation.record_run(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            prompt_version=self.prompt_version,
            prompt_hash=prompt_hash,
            system_prompt=self.system_prompt,
            llm_provider=info.provider,
            llm_model=info.model,
            llm_config=info.config,
            input_messages=input_messages,
            tool_trace=tool_trace,
            mutation_receipts=mutation_receipts,
            final_content=final_content,
            rounds=rounds,
            status=status,
            error=error,
            commit=commit,
        )
