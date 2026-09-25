# 0076 — Telegram single-user security and adapter state

Status: issued implementation spec for batch 0071–0080.

## Objective

Add Telegram-specific adapter state without introducing general users/channels.

## Configuration

Required:

- AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN;
- AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID.

Optional source label may override the default telegram:<user_id> audit metadata.

## Accepted messages

Invoke the application only when:

- message.from.id equals allowed user ID;
- chat.type is private;
- text is nonblank.

Unauthorized, group/channel and non-text updates never reach AgentRunner.

## Persistent adapter state

Persist:

- Telegram private chat_id -> application conversation_id;
- durable last acknowledged update id / next offset.

This is Telegram adapter storage, not inventory ownership.

First accepted text message may allocate an application conversation; later messages reuse it.

## Migration/tests

Add only the minimal adapter tables/columns required. Verify fresh/upgrade/wheel migration behavior.


## Issued persistence decision

Use Telegram-specific persistence, not generic accounts/channels.

Minimum durable concepts:

- private Telegram chat ID -> application conversation ID binding;
- polling next-offset / last-acknowledged update state.

Use integer storage capable of Telegram's full ID/update ranges.

Configuration remains environment-backed:

- AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN
- AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID

The token must not be stored in DB.

Rejected/non-private/non-text updates never invoke the application. They may still be safely acknowledged by the polling state machine in 0077 so one rejected update cannot block the poller forever.

## Focused verification

Create/extend `tests/test_telegram_adapter.py`.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_telegram_adapter.py tests/test_migrations.py tests/test_wheel_migrations.py tests/test_trace_config_privacy.py -k "telegram or allowed_user or private or mapping or checkpoint or migration or token"
    make migration-check
    make compile
    git diff --check
