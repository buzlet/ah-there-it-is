# 0076 — Telegram single-user security and adapter state

Status: draft task spec; reconcile after 0061-0070 merge.

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
