"""Minimal persisted human-visible conversation history."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Conversation, Message, utc_now
from ah_there_it_is.domain.exceptions import EntityNotFoundError


class ConversationService:
    AGENT_CONTEXT_MESSAGE_LIMIT = 40

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self) -> Conversation:
        conversation = Conversation()
        self.session.add(conversation)
        self._commit(conversation)
        return conversation

    def get(self, conversation_id: int) -> Conversation:
        conversation = self.session.get(Conversation, conversation_id)
        if conversation is None:
            raise EntityNotFoundError(
                f"conversation id={conversation_id} does not exist"
            )
        return conversation

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        *,
        commit: bool = True,
    ) -> Message:
        if role not in {"user", "assistant"}:
            raise ValueError("only user/assistant messages are persisted")
        conversation = self.get(conversation_id)
        message = Message(conversation=conversation, role=role, content=content)
        conversation.updated_at = utc_now()
        self.session.add(message)
        self._persist(message, commit=commit)
        return message

    def list_messages(self, conversation_id: int) -> list[Message]:
        self.get(conversation_id)
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_agent_context_messages(self, conversation_id: int) -> list[Message]:
        self.get(conversation_id)
        newest_first = list(self.session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.desc())
            .limit(self.AGENT_CONTEXT_MESSAGE_LIMIT)
        ))
        newest_first.reverse()
        if newest_first and newest_first[0].role == "assistant":
            newest_first.pop(0)
        return newest_first

    def _commit(self, entity: object) -> None:
        self._persist(entity, commit=True)

    def _persist(self, entity: object, *, commit: bool) -> None:
        try:
            if commit:
                self.session.commit()
            else:
                self.session.flush()
        except Exception:
            if commit:
                self.session.rollback()
            raise
        self.session.refresh(entity)
