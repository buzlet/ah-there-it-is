from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ah_there_it_is.db.models import (
    ChatRequestRecord,
    Conversation,
    TelegramFailureNotice,
)
from ah_there_it_is.services.chat_requests import ChatRequestService
from ah_there_it_is.telegram.adapter import (
    NO_MUTATION_FAILURE_TEXT,
    UNCERTAIN_FAILURE_TEXT,
    TelegramAdapter,
    TelegramRecoveryRequiredError,
)
from ah_there_it_is.telegram.client import (
    TelegramChat,
    TelegramMessage,
    TelegramUpdate,
    TelegramUser,
)
from ah_there_it_is.telegram.polling import TelegramPollingService


def _update(update_id: int, text: str) -> TelegramUpdate:
    return TelegramUpdate(
        update_id=update_id,
        message=TelegramMessage(
            message_id=update_id,
            chat=TelegramChat(id=7, type="private"),
            from_user=TelegramUser(id=7),
            text=text,
        ),
    )


class _Client:
    def __init__(self, updates: list[TelegramUpdate]) -> None:
        self.updates = updates
        self.sent: list[tuple[int, str]] = []
        self.fail_sends = 0

    def get_updates(self, *, offset: int, timeout: int, limit: int):
        return [update for update in self.updates if update.update_id >= offset]

    def send_message(self, chat_id: int, text: str):
        if self.fail_sends:
            self.fail_sends -= 1
            raise RuntimeError("reply transport failed")
        self.sent.append((chat_id, text))
        return ()


class _FailThenSuccess:
    def __init__(self, session) -> None:
        self.session = session
        self.calls: list[str] = []
        self.mutations = 0

    def execute_chat(self, message: str, **kwargs):
        self.calls.append(message)
        if message == "fail safely":
            def fail(_commit):
                raise RuntimeError("provider=private internal detail")

            return ChatRequestService(self.session).execute(
                request_key=kwargs["request_key"],
                message=message,
                conversation_id=kwargs["conversation_id"],
                source_identity=kwargs["source_identity"],
                operation=fail,
            )
        self.mutations += 1
        return SimpleNamespace(
            result=SimpleNamespace(conversation_id=41, content="Ответ готов.")
        )


def test_proven_no_mutation_failure_is_replied_and_does_not_block_next_update(session) -> None:
    session.add(Conversation(id=41))
    session.commit()
    app = _FailThenSuccess(session)
    client = _Client([_update(10, "fail safely"), _update(11, "continue")])
    adapter = TelegramAdapter(session, app, client, allowed_user_id=7)

    result = TelegramPollingService(adapter, client).run_once()

    assert result.processed == 2
    assert result.next_offset == 12
    assert app.calls == ["fail safely", "continue"]
    assert app.mutations == 1
    assert client.sent == [
        (7, NO_MUTATION_FAILURE_TEXT),
        (7, "Ответ готов."),
    ]
    assert "provider" not in client.sent[0][1]
    record = ChatRequestService(session).get("telegram:10")
    assert record is not None and record.status == "failed" and record.agent_run_id is None
    notice = session.get(TelegramFailureNotice, 10)
    assert notice is not None and notice.notice_kind == "no_mutation"


def test_no_mutation_failure_notice_is_not_repeated_after_checkpoint_retry(session) -> None:
    app = _FailThenSuccess(session)
    update = _update(20, "fail safely")
    client = _Client([update])
    adapter = TelegramAdapter(session, app, client, allowed_user_id=7)
    polling = TelegramPollingService(adapter, client)
    original_ack = adapter.acknowledge_update
    failures = 1

    def fail_first_ack(update_id: int) -> int:
        nonlocal failures
        if failures:
            failures -= 1
            raise RuntimeError("checkpoint failure")
        return original_ack(update_id)

    adapter.acknowledge_update = fail_first_ack  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="checkpoint failure"):
        polling.run_once()
    assert adapter.next_offset() == 0
    assert client.sent == [(7, NO_MUTATION_FAILURE_TEXT)]

    result = polling.run_once()

    assert result.next_offset == 21
    assert result.processed == 1
    assert client.sent == [(7, NO_MUTATION_FAILURE_TEXT)]
    assert app.calls == ["fail safely"]
    assert app.mutations == 0


def test_uncertain_failure_sends_one_conservative_notice_and_stays_unacked(session) -> None:
    text = "Создай предмет, если его нет"
    session.add(
        ChatRequestRecord(
            request_key="telegram:30",
            requested_conversation_id=None,
            message=text,
            source_identity="telegram:7",
            status="processing",
        )
    )
    session.commit()
    app = _FailThenSuccess(session)
    client = _Client([_update(30, text)])
    adapter = TelegramAdapter(session, app, client, allowed_user_id=7)
    polling = TelegramPollingService(adapter, client)

    with pytest.raises(TelegramRecoveryRequiredError, match="30"):
        polling.run_once()
    assert adapter.next_offset() == 0
    assert client.sent == [(7, UNCERTAIN_FAILURE_TEXT)]
    notice = session.get(TelegramFailureNotice, 30)
    assert notice is not None and notice.notice_kind == "uncertain"
    with pytest.raises(TelegramRecoveryRequiredError, match="30"):
        polling.run_once()
    assert adapter.next_offset() == 0
    assert client.sent == [(7, UNCERTAIN_FAILURE_TEXT)]
    assert app.calls == []
    assert session.scalar(select(ChatRequestRecord.id).where(
        ChatRequestRecord.request_key == "telegram:30"
    )) is not None

    with OrmSession(bind=session.get_bind()) as restarted_session:
        restarted_adapter = TelegramAdapter(
            restarted_session, app, client, allowed_user_id=7
        )
        with pytest.raises(TelegramRecoveryRequiredError, match="30"):
            TelegramPollingService(restarted_adapter, client).run_once()
        assert restarted_adapter.next_offset() == 0
    assert client.sent == [(7, UNCERTAIN_FAILURE_TEXT)]


def test_progress_transport_failure_cannot_fail_or_mutate_request(
    session, monkeypatch
) -> None:
    from ah_there_it_is.telegram import polling as polling_module
    from ah_there_it_is.telegram.progress import TelegramDraftProgress

    session.add(Conversation(id=41))
    session.commit()
    app = _FailThenSuccess(session)
    client = _Client([_update(40, "continue")])

    class FailingDraftClient(_Client):
        def send_message_draft(self, *_args) -> None:
            raise RuntimeError("draft transport unavailable")

    class ImmediateProgress:
        def __init__(self, *_args, **_kwargs) -> None:
            self.progress = TelegramDraftProgress(
                FailingDraftClient([]), 7, 128
            )

        def __enter__(self):
            self.progress._send("Обрабатываю запрос.")
            return self

        def __exit__(self, *_args) -> None:
            pass

    # Exercise the actual draft failure handler immediately, without wall time.
    monkeypatch.setattr(polling_module, "TelegramDraftProgress", ImmediateProgress)
    result = TelegramPollingService(
        TelegramAdapter(session, app, client, allowed_user_id=7), client
    ).run_once()

    assert result.processed == 1
    assert result.next_offset == 41
    assert app.calls == ["continue"]
    assert app.mutations == 1
    assert client.sent == [(7, "Ответ готов.")]
