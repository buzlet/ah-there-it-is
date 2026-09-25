"""Shared chat orchestration for Web and text adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ah_there_it_is.services.chat_requests import (
    ChatRequestService,
    IdempotentExecution,
)

if TYPE_CHECKING:
    from ah_there_it_is.agent.protocol import LLMClient
    from ah_there_it_is.agent.runner import AgentRunResult


class ChatApplicationService:
    """Own the common AgentRunner and keyed request transaction boundary."""

    def __init__(
        self,
        session,
        llm_factory: Callable[[], "LLMClient"],
        *,
        max_rounds: int = 8,
        system_prompt: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        self.session = session
        self.llm_factory = llm_factory
        self.max_rounds = max_rounds
        if system_prompt is None or prompt_version is None:
            from ah_there_it_is.agent.runner import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION

            self.system_prompt = system_prompt or SYSTEM_PROMPT
            self.prompt_version = prompt_version or SYSTEM_PROMPT_VERSION
        else:
            self.system_prompt = system_prompt
            self.prompt_version = prompt_version

    def execute_chat(
        self,
        message: str,
        *,
        conversation_id: int | None = None,
        request_key: str | None = None,
        source_identity: str | None = None,
    ) -> IdempotentExecution:
        from ah_there_it_is.agent.runner import AgentRunner

        def operation(commit_on_success: bool) -> AgentRunResult:
            llm = self.llm_factory()
            try:
                return AgentRunner(
                    self.session,
                    llm,
                    max_rounds=self.max_rounds,
                    system_prompt=self.system_prompt,
                    prompt_version=self.prompt_version,
                ).run(
                    message,
                    conversation_id=conversation_id,
                    commit_on_success=commit_on_success,
                )
            finally:
                close = getattr(llm, "close", None)
                if callable(close):
                    close()

        return ChatRequestService(self.session).execute(
            request_key=request_key,
            message=message,
            conversation_id=conversation_id,
            source_identity=source_identity,
            operation=operation,
        )

    def recover_chat(
        self,
        *,
        source_request_key: str,
        new_request_key: str,
        recovery_note: str,
        source_identity: str | None = None,
    ) -> IdempotentExecution:
        from ah_there_it_is.agent.runner import AgentRunner

        requests = ChatRequestService(self.session)
        source = requests.get(source_request_key)
        if source is None:
            # Let ChatRequestService produce its canonical not-found error.
            return requests.recover(
                source_request_key=source_request_key,
                new_request_key=new_request_key,
                recovery_note=recovery_note,
                source_identity=source_identity,
                operation=lambda _commit: self._unreachable(),
            )

        def operation(commit_on_success: bool) -> AgentRunResult:
            llm = self.llm_factory()
            try:
                return AgentRunner(
                    self.session,
                    llm,
                    max_rounds=self.max_rounds,
                    system_prompt=self.system_prompt,
                    prompt_version=self.prompt_version,
                ).run(
                    source.message,
                    conversation_id=source.requested_conversation_id,
                    commit_on_success=commit_on_success,
                )
            finally:
                close = getattr(llm, "close", None)
                if callable(close):
                    close()

        return requests.recover(
            source_request_key=source_request_key,
            new_request_key=new_request_key,
            recovery_note=recovery_note,
            source_identity=source_identity,
            operation=operation,
        )

    @staticmethod
    def _unreachable() -> AgentRunResult:
        raise RuntimeError("chat recovery source disappeared")
