# 0087 — Security, privacy and malformed-boundary hardening

## Objective

Try to break external/application boundaries without network access. Correct only concrete validation or secret-persistence failures.

## Required work

Use synthetic secret markers and malformed values through:

- Telegram API response/error parsing;
- Telegram update/message/chat/user IDs;
- source labels;
- request keys;
- Web chat/media payloads;
- Agent tool schemas;
- media provider/reference/caption/order;
- exception messages.

Search resulting durable/application evidence for the synthetic secret:

- ChatRequestRecord;
- AgentRunLog/tool trace;
- Event payload;
- receipts;
- source identity;
- user-visible error strings.

Verify unauthorized/non-private/non-text Telegram input cannot invoke the application service.

Verify malformed values fail at a stable boundary rather than relying on SQLite coercion or Python `bool` being an `int`.

Do not add generic security frameworks, authentication systems or new dependencies.

## Focused verification

    .venv/bin/python -m pytest -q       tests/test_trace_config_privacy.py       tests/test_telegram_client.py       tests/test_telegram_adapter.py       tests/test_telegram_runtime.py       tests/test_chat_application_service.py       tests/test_app.py       tests/test_agent.py       tests/test_item_media.py
    make compile
    git diff --check
