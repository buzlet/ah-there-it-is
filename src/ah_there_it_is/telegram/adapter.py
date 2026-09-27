"""Single-user private-text Telegram adapter and its durable local state."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from ah_there_it_is.db.models import (
    ChatRequestRecord,
    TelegramChatBinding,
    TelegramFailureNotice,
    TelegramPollingState,
    utc_now,
)
from ah_there_it_is.services.chat_requests import ChatRequestService, IdempotentExecution
from ah_there_it_is.telegram.client import (
    TelegramCallbackQuery, TelegramChat, TelegramMessage, TelegramUpdate, TelegramUser,
)
from ah_there_it_is.telegram.navigation import (
    TelegramLocationBrowser,
    TelegramLocationRenderer,
    TelegramNavigationAction,
    parse_navigation_callback,
)


NO_MUTATION_FAILURE_TEXT = (
    "Не получилось завершить этот запрос. Я ничего не менял. "
    "Попробуйте сформулировать его немного иначе или повторить позже."
)
UNCERTAIN_FAILURE_TEXT = (
    "Не получилось завершить запрос. Я остановился, чтобы не внести данные дважды. "
    "Запрос сохранён для безопасного восстановления."
)
STALE_NAVIGATION_TEXT = (
    "Эта кнопка устарела. Откройте /locations, чтобы продолжить."
)
_LOCATIONS_COMMAND = re.compile(r"^/locations(?:@[a-zA-Z0-9_]+)?(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class TelegramAdapterResult:
    accepted: bool
    invoked: bool
    chat_id: int | None = None
    conversation_id: int | None = None
    content: str | None = None
    reason: str | None = None
    sent_messages: tuple[TelegramMessage, ...] = ()
    handled_failure: bool = False


class TelegramRecoveryRequiredError(RuntimeError):
    """An interrupted Telegram update needs an explicit operator decision."""


class TelegramRecoveryError(RuntimeError):
    """The requested Telegram recovery is not safe for this durable state."""


class TelegramAdapter:
    """Apply the single-user/private-text policy before calling the application."""

    POLLING_STATE_ID = 1

    def __init__(
        self,
        session: OrmSession,
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
        if isinstance(update, TelegramUpdate) and update.callback_query is not None:
            return self._callback_rejection_reason(update.callback_query) is None
        return self._rejection_reason(update) is None

    def process_update(
        self,
        update: TelegramUpdate,
        *,
        request_key: str | None = None,
        send_reply: bool = True,
    ) -> TelegramAdapterResult:
        if isinstance(update, TelegramUpdate) and update.callback_query is not None:
            return self.process_callback_update(update)
        rejection = self._rejection_reason(update)
        if rejection is not None:
            return TelegramAdapterResult(
                accepted=False,
                invoked=False,
                reason=rejection,
            )
        assert update.message is not None
        message = update.message
        if _LOCATIONS_COMMAND.match(message.text or ""):
            view = TelegramLocationBrowser(self.session).root_page()
            renderer = TelegramLocationRenderer()
            keyboard = renderer.root_keyboard(view)
            sent = tuple(
                self.client.send_message(
                    message.chat.id,
                    renderer.render_root(view),
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            )
            return TelegramAdapterResult(
                accepted=True,
                invoked=False,
                chat_id=message.chat.id,
                content=renderer.render_root(view),
                sent_messages=sent,
            )
        binding = self.session.get(TelegramChatBinding, message.chat.id)
        conversation_id = binding.conversation_id if binding is not None else None
        # A first delivery reserves the request before the chat binding is
        # persisted.  On a send/checkpoint retry the binding is present, but
        # the keyed request must be replayed with the exact conversation value
        # used for that reservation (often ``None`` for the first message).
        # Otherwise ChatRequestService would mistake a delivery retry for a
        # conflicting request.
        prior_request = None
        if request_key is not None:
            prior_request = self.session.scalar(
                select(ChatRequestRecord).where(
                    ChatRequestRecord.request_key == request_key
                )
            )
            if prior_request is not None:
                conversation_id = prior_request.requested_conversation_id
        if prior_request is not None and prior_request.status in {"processing", "failed"}:
            if prior_request.source_identity != self.source_identity:
                self._notify_uncertain_failure(update, request_key or "")
                raise TelegramRecoveryRequiredError(
                    f"Telegram update {update.update_id} has inconsistent request ownership"
                )
            if prior_request.message != message.text.strip():
                self._notify_uncertain_failure(update, request_key or "")
                raise TelegramRecoveryRequiredError(
                    f"Telegram update {update.update_id} differs from its durable request"
                )
            try:
                recovered = self._completed_recovery(prior_request, update.update_id)
            except TelegramRecoveryError:
                self._notify_uncertain_failure(update, request_key or "")
                raise TelegramRecoveryRequiredError(
                    f"Telegram update {update.update_id} needs safe recovery"
                ) from None
            if recovered is None:
                if self._proven_no_mutation_failure(
                    request_key, message.text.strip()
                ):
                    sent = self._notify_failure(
                        update.update_id,
                        request_key or f"telegram:{update.update_id}",
                        "no_mutation",
                        NO_MUTATION_FAILURE_TEXT,
                        message.chat.id,
                    )
                    return TelegramAdapterResult(
                        accepted=True,
                        invoked=True,
                        chat_id=message.chat.id,
                        conversation_id=conversation_id,
                        content=NO_MUTATION_FAILURE_TEXT,
                        reason="handled application failure",
                        sent_messages=sent,
                        handled_failure=True,
                    )
                self._notify_uncertain_failure(update, request_key or "")
                raise TelegramRecoveryRequiredError(
                    f"Telegram update {update.update_id} has a {prior_request.status} "
                    "request; stop the poller and use telegram-recover"
                )
            result = ChatRequestService(self.session).completed_result(recovered)
        else:
            try:
                execution = self.chat_service.execute_chat(
                    message.text.strip(),
                    conversation_id=conversation_id,
                    request_key=request_key,
                    source_identity=self.source_identity,
                )
            except Exception:
                if self._proven_no_mutation_failure(
                    request_key, message.text.strip()
                ):
                    sent = self._notify_failure(
                        update.update_id,
                        request_key or f"telegram:{update.update_id}",
                        "no_mutation",
                        NO_MUTATION_FAILURE_TEXT,
                        message.chat.id,
                    )
                    return TelegramAdapterResult(
                        accepted=True,
                        invoked=True,
                        chat_id=message.chat.id,
                        conversation_id=conversation_id,
                        content=NO_MUTATION_FAILURE_TEXT,
                        reason="handled application failure",
                        sent_messages=sent,
                        handled_failure=True,
                    )
                self._notify_uncertain_failure(update, request_key or "")
                raise TelegramRecoveryRequiredError(
                    f"Telegram update {update.update_id} needs safe recovery"
                ) from None
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

    def process_callback_update(self, update: TelegramUpdate) -> TelegramAdapterResult:
        """Answer every callback promptly; authorized navigation is read-only."""
        callback = update.callback_query
        if callback is None:
            return TelegramAdapterResult(
                accepted=False, invoked=False, reason="update has no callback query"
            )
        answer = getattr(self.client, "answer_callback_query", None)
        if callable(answer) and isinstance(callback.id, str) and callback.id:
            try:
                answer(callback.id)
            except Exception:
                # The query answer is advisory; it must not affect inventory or
                # stop a read-only navigation update.
                pass
        rejection = self._callback_rejection_reason(callback)
        if rejection is not None:
            return TelegramAdapterResult(
                accepted=False, invoked=False, reason=rejection
            )
        assert callback.message is not None
        message = callback.message
        action = parse_navigation_callback(callback.data)
        renderer = TelegramLocationRenderer()
        try:
            rendered = self._render_navigation_action(action, renderer)
        except (ValueError, TelegramRecoveryError):
            rendered = None
        if rendered is None:
            text = STALE_NAVIGATION_TEXT
            keyboard: dict[str, object] = {"inline_keyboard": []}
        else:
            text, keyboard = rendered
        edit = getattr(self.client, "edit_message_text", None)
        if callable(edit):
            try:
                edit(
                    message.chat.id,
                    message.message_id,
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception:
                # A stale/uneditable navigation message is a transport UX issue,
                # never a reason to enter the inventory mutation path.
                pass
        return TelegramAdapterResult(
            accepted=True,
            invoked=False,
            chat_id=message.chat.id,
            content=text,
            reason=None if rendered is not None else "malformed or stale navigation callback",
        )

    def _render_navigation_action(
        self,
        action: TelegramNavigationAction | None,
        renderer: TelegramLocationRenderer,
    ) -> tuple[str, dict[str, object]] | None:
        if action is None:
            return None
        browser = TelegramLocationBrowser(self.session)
        if action.kind == "root":
            view = browser.root_page(action.page)
            return renderer.render_root(view), (
                renderer.root_keyboard(view) or {"inline_keyboard": []}
            )
        assert action.location_id is not None
        view = browser.location_contents(
            action.location_id,
            root_page=action.root_page,
            item_page=action.page if action.kind == "items" else 1,
            child_page=action.page if action.kind == "children" else 1,
        )
        if view is None:
            return None
        if action.kind == "back":
            if view.parent_id is None:
                root = browser.root_page(action.root_page)
                return renderer.render_root(root), (
                    renderer.root_keyboard(root) or {"inline_keyboard": []}
                )
            view = browser.location_contents(view.parent_id, root_page=action.root_page)
            if view is None:
                return None
        return (
            renderer.render_location(view),
            renderer.location_keyboard(view),
        )

    def _callback_rejection_reason(
        self, callback: TelegramCallbackQuery
    ) -> str | None:
        if (
            not isinstance(callback.from_user, TelegramUser)
            or type(callback.from_user.id) is not int
            or callback.from_user.id != self.allowed_user_id
        ):
            return "callback sender is not allowed"
        message = callback.message
        if (
            message is None
            or callback.inline_message_id is not None
            or not isinstance(message, TelegramMessage)
            or type(message.message_id) is not int
            or message.message_id <= 0
            or not isinstance(message.chat, TelegramChat)
            or message.chat.type != "private"
            or type(message.chat.id) is not int
            or message.chat.id != self.allowed_user_id
            or not isinstance(message.from_user, TelegramUser)
            or message.from_user.is_bot is not True
        ):
            return "callback context is not an authorized private bot message"
        return None

    def _proven_no_mutation_failure(
        self, request_key: str | None, message: str
    ) -> bool:
        """Trust only a durable terminal request with no attached successful run."""
        if not isinstance(request_key, str) or not request_key:
            return False
        try:
            with OrmSession(bind=self.session.get_bind()) as durable:
                record = durable.scalar(
                    select(ChatRequestRecord).where(
                        ChatRequestRecord.request_key == request_key
                    )
                )
                return bool(
                    record is not None
                    and record.status == "failed"
                    and record.agent_run_id is None
                    and record.message == message
                    and record.source_identity == self.source_identity
                )
        except Exception:
            return False

    def _notify_uncertain_failure(
        self, update: TelegramUpdate, request_key: str
    ) -> tuple[TelegramMessage, ...]:
        if update.message is None:
            return ()
        return self._notify_failure(
            update.update_id,
            request_key or f"telegram:{update.update_id}",
            "uncertain",
            UNCERTAIN_FAILURE_TEXT,
            update.message.chat.id,
        )

    def _notify_failure(
        self,
        update_id: int,
        request_key: str,
        notice_kind: str,
        content: str,
        chat_id: int,
    ) -> tuple[TelegramMessage, ...]:
        existing = self._failure_notice(update_id)
        if existing is not None:
            if existing.request_key != request_key:
                raise TelegramRecoveryError(
                    "Telegram failure notice belongs to a different request"
                )
            return ()

        sent = tuple(self.client.send_message(chat_id, content))
        try:
            with OrmSession(bind=self.session.get_bind()) as durable:
                existing = durable.get(TelegramFailureNotice, update_id)
                if existing is None:
                    durable.add(
                        TelegramFailureNotice(
                            update_id=update_id,
                            request_key=request_key,
                            notice_kind=notice_kind,
                            sent_at=utc_now(),
                        )
                    )
                    durable.commit()
                elif existing.request_key != request_key:
                    raise TelegramRecoveryError(
                        "Telegram failure notice belongs to a different request"
                    )
        except Exception:
            # A commit error may have happened after SQLite committed. Reconcile
            # through a fresh Session before allowing a later poll to resend.
            if self._failure_notice(update_id, request_key=request_key) is None:
                raise
        return sent

    def _failure_notice(
        self, update_id: int, *, request_key: str | None = None
    ) -> TelegramFailureNotice | None:
        try:
            with OrmSession(bind=self.session.get_bind()) as durable:
                notice = durable.get(TelegramFailureNotice, update_id)
                if notice is not None and request_key is not None:
                    if notice.request_key != request_key:
                        raise TelegramRecoveryError(
                            "Telegram failure notice belongs to a different request"
                        )
                    return notice
                return notice
        except TelegramRecoveryError:
            raise
        except Exception:
            return None

    def recovery_status(self, update_id: int) -> dict[str, object]:
        source = self._recovery_source(update_id)
        attempts = self._recovery_lineage(source, update_id)[1:]
        return {
            "update_id": update_id,
            "request_status": source.status,
            "request_has_run": source.agent_run_id is not None,
            "attempts": [
                {"request_key": attempt.request_key, "status": attempt.status}
                for attempt in attempts
            ],
        }

    def recover_update(self, update_id: int, *, attempt: int) -> IdempotentExecution:
        """Operator retry with a new durable key; never retry the original key."""
        if type(attempt) is not int or attempt < 1:
            raise TelegramRecoveryError("recovery attempt must be a positive integer")
        source = self._recovery_source(update_id)
        lineage = self._recovery_lineage(source, update_id)
        if lineage[-1].status == "completed":
            raise TelegramRecoveryError("Telegram update already has a completed recovery")
        key = f"telegram-recovery:{update_id}:{attempt}"
        if any(record.request_key == key for record in lineage):
            raise TelegramRecoveryError("recovery attempt key was already used")
        recover_chat = getattr(self.chat_service, "recover_chat", None)
        if not callable(recover_chat):
            raise TelegramRecoveryError("chat service does not support recovery")
        return recover_chat(
            source_request_key=lineage[-1].request_key,
            new_request_key=key,
            recovery_note=f"Telegram operator confirmed atomic rollback; attempt {attempt}",
            source_identity=self.source_identity,
        )

    def _recovery_source(self, update_id: int) -> ChatRequestRecord:
        if type(update_id) is not int or update_id < 0 or update_id >= 2**63 - 1:
            raise TelegramRecoveryError("update id is invalid")
        source = ChatRequestService(self.session).get(f"telegram:{update_id}")
        if source is None:
            raise TelegramRecoveryError("Telegram update has no durable request")
        if source.source_identity != self.source_identity:
            raise TelegramRecoveryError("Telegram request source identity changed")
        if source.status not in {"processing", "failed"} or source.agent_run_id is not None:
            raise TelegramRecoveryError("Telegram update has no recoverable request")
        return source

    def _recovery_lineage(
        self, source: ChatRequestRecord, update_id: int
    ) -> list[ChatRequestRecord]:
        lineage = [source]
        while True:
            children = list(self.session.scalars(
                select(ChatRequestRecord)
                .where(ChatRequestRecord.recovered_from_id == lineage[-1].id)
                .order_by(ChatRequestRecord.id)
            ))
            if not children:
                return lineage
            if len(children) != 1:
                raise TelegramRecoveryError("Telegram recovery history is ambiguous")
            child = children[0]
            if (
                not child.request_key.startswith(f"telegram-recovery:{update_id}:")
                or child.message != source.message
                or child.requested_conversation_id != source.requested_conversation_id
                or child.source_identity != source.source_identity
                or child.agent_run_id is not None and child.status != "completed"
                or len(lineage) >= 100
            ):
                raise TelegramRecoveryError("Telegram recovery history is inconsistent")
            lineage.append(child)

    def _completed_recovery(
        self, source: ChatRequestRecord, update_id: int
    ) -> ChatRequestRecord | None:
        lineage = self._recovery_lineage(source, update_id)
        if any(record.status == "completed" for record in lineage[1:-1]):
            raise TelegramRecoveryError("Telegram recovery continued after completion")
        return lineage[-1] if len(lineage) > 1 and lineage[-1].status == "completed" else None

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
