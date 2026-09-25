"""Single-user private-text Telegram adapter and its durable local state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ah_there_it_is.db.models import (
    ChatRequestRecord,
    TelegramChatBinding,
    TelegramPollingState,
    utc_now,
)
from ah_there_it_is.telegram.client import (
    TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser,
)


@dataclass(frozen=True)
class TelegramAdapterResult:
    accepted: bool
    invoked: bool
    chat_id: int | None = None
    conversation_id: int | None = None
    content: str | None = None
    reason: str | None = None
    sent_messages: tuple[TelegramMessage, ...] = ()


class TelegramAdapter:
    """Apply the single-user/private-text policy before calling the application."""

    POLLING_STATE_ID = 1

    def __init__(
        self,
        session: Session,
        chat_service: Any,
        client: Any,
        *,
        allowed_user_id: int,
        source_label: str | None = None,
    ) -> None:
        if type(allowed_user_id) is not int or allowed_user_id <= 0:
            raise ValueError("allowed_user_id must be a positive integer")
        self.session = session
        self.chat_service = chat_service
        self.client = client
        self.allowed_user_id = allowed_user_id
        label = source_label.strip() if source_label is not None else ""
        if len(label) > 200:
            raise ValueError("source_label must be at most 200 characters")
        self.source_identity = label or f"telegram:{allowed_user_id}"

    def accepts(self, update: TelegramUpdate) -> bool:
        return self._rejection_reason(update) is None

    def process_update(
        self,
        update: TelegramUpdate,
        *,
        request_key: str | None = None,
        send_reply: bool = True,
    ) -> TelegramAdapterResult:
        rejection = self._rejection_reason(update)
        if rejection is not None:
            return TelegramAdapterResult(
                accepted=False,
                invoked=False,
                reason=rejection,
            )
        assert update.message is not None
        message = update.message
        binding = self.session.get(TelegramChatBinding, message.chat.id)
        conversation_id = binding.conversation_id if binding is not None else None
        # A first delivery reserves the request before the chat binding is
        # persisted.  On a send/checkpoint retry the binding is present, but
        # the keyed request must be replayed with the exact conversation value
        # used for that reservation (often ``None`` for the first message).
        # Otherwise ChatRequestService would mistake a delivery retry for a
        # conflicting request.
        if request_key is not None:
            prior_request = self.session.scalar(
                select(ChatRequestRecord).where(
                    ChatRequestRecord.request_key == request_key
                )
            )
            if prior_request is not None:
                conversation_id = prior_request.requested_conversation_id
        execution = self.chat_service.execute_chat(
            message.text.strip(),
            conversation_id=conversation_id,
            request_key=request_key,
            source_identity=self.source_identity,
        )
        result = execution.result
        if binding is None:
            binding = TelegramChatBinding(
                chat_id=message.chat.id,
                conversation_id=result.conversation_id,
            )
            self.session.add(binding)
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                binding = self.session.get(TelegramChatBinding, message.chat.id)
                if binding is None:
                    raise
        sent: tuple[TelegramMessage, ...] = ()
        if send_reply:
            sent = tuple(self.client.send_message(message.chat.id, result.content))
        return TelegramAdapterResult(
            accepted=True,
            invoked=True,
            chat_id=message.chat.id,
            conversation_id=result.conversation_id,
            content=result.content,
            sent_messages=sent,
        )

    def conversation_id_for_chat(self, chat_id: int) -> int | None:
        binding = self.session.get(TelegramChatBinding, chat_id)
        return binding.conversation_id if binding is not None else None

    def next_offset(self) -> int:
        state = self.session.get(TelegramPollingState, self.POLLING_STATE_ID)
        return state.next_offset if state is not None else 0

    def acknowledge_update(self, update_id: int) -> int:
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            raise ValueError("update_id must be a non-negative integer")
        state = self.session.get(TelegramPollingState, self.POLLING_STATE_ID)
        if state is None:
            state = TelegramPollingState(id=self.POLLING_STATE_ID, next_offset=0)
            self.session.add(state)
            self.session.flush()
        state.next_offset = max(state.next_offset, update_id + 1)
        state.updated_at = utc_now()
        self.session.commit()
        return state.next_offset

    def set_next_offset(self, next_offset: int) -> int:
        if isinstance(next_offset, bool) or not isinstance(next_offset, int) or next_offset < 0:
            raise ValueError("next_offset must be a non-negative integer")
        state = self.session.get(TelegramPollingState, self.POLLING_STATE_ID)
        if state is None:
            state = TelegramPollingState(id=self.POLLING_STATE_ID, next_offset=next_offset)
            self.session.add(state)
        else:
            state.next_offset = next_offset
            state.updated_at = utc_now()
        self.session.commit()
        return next_offset

    def _rejection_reason(self, update: TelegramUpdate) -> str | None:
        if not isinstance(update, TelegramUpdate) or update.message is None:
            return "update has no text message"
        if type(update.update_id) is not int or not 0 <= update.update_id < 2**63 - 1:
            return "update id is malformed"
        message = update.message
        if not isinstance(message, TelegramMessage) or (
            type(message.message_id) is not int or message.message_id <= 0
        ):
            return "message is malformed"
        if not isinstance(message.chat, TelegramChat) or (
            type(message.chat.id) is not int or message.chat.id <= 0
        ):
            return "chat is malformed"
        if not isinstance(message.from_user, TelegramUser) or (
            type(message.from_user.id) is not int
            or message.from_user.id != self.allowed_user_id
        ):
            return "sender is not allowed"
        if message.chat.type != "private":
            return "chat is not private"
        if not isinstance(message.text, str) or not message.text.strip():
            return "message text is blank"
        return None


SingleUserTelegramAdapter = TelegramAdapter
