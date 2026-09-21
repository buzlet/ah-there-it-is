"""Minimal persisted human-visible conversation history."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import Conversation, Message, utc_now
from ah_there_it_is.domain.exceptions import EntityNotFoundError


class ConversationService:
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

    def add_message(self, conversation_id: int, role: str, content: str) -> Message:
        if role not in {"user", "assistant"}:
            raise ValueError("only user/assistant messages are persisted")
        conversation = self.get(conversation_id)
        message = Message(conversation=conversation, role=role, content=content)
        conversation.updated_at = utc_now()
        self.session.add(message)
        self._commit(message)
        return message

    def list_messages(self, conversation_id: int) -> list[Message]:
        self.get(conversation_id)
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
        )
        return list(self.session.scalars(stmt))

    def _commit(self, entity: object) -> None:
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(entity)
