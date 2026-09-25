# Single-user Telegram bot adapter

Status: **accepted core-MVP design** on 2026-09-25. Stored on the temporary planning branch until 0061-0070 merges.

Authoritative umbrella decision:
`agent-tasks/parallel/core-media-telegram-decision.md`

## Goal

Provide a working single-user Telegram text interface to the existing inventory application without adding Telegram concepts to inventory domain code.

## Architecture

```text
Telegram long polling
  -> TelegramBotAdapter
  -> shared application ChatApplicationService
  -> ChatRequestService / AgentRunner
  -> inventory
  -> response
  -> Telegram sendMessage
```

Refactor existing web-chat orchestration into a reusable application-level service if needed. Web and Telegram must not maintain separate mutation/idempotency logic.

## Configuration

Environment-backed settings:

```text
AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN
AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID
```

Optional operational settings may cover poll timeout/backoff.

Never log/persist the bot token.

Do not add generic accounts/users/channels.

## Accepted input

Core MVP accepts only:

- private Telegram chat;
- `from.id == configured allowed user ID`;
- nonblank text message.

Other senders/chats/media are ignored or rejected before invoking the inventory application.

## Adapter state

Persist Telegram-specific state outside inventory domain entities.

Minimum state:

```text
telegram chat id -> application conversation_id
last acknowledged update id / next offset
```

One logical application user remains authoritative.

## Idempotency

For every accepted update, derive:

```text
request_key = "telegram:" + update_id
```

Feed it into the existing application request-key path.

Repeated delivery of one Update must replay the prior result and never reapply inventory mutations.

## Polling

Use Bot API `getUpdates` long polling only.

No webhook implementation in core MVP.

Do not run long polling and webhook mode simultaneously.

Advance the durable local checkpoint only after application processing and reply attempt according to the adapter state machine.

## Delivery semantics

Inventory mutation correctness is stronger than outbound delivery:

- application effect: exactly once under request-key semantics;
- Telegram reply: best-effort at least once.

A crash after Telegram accepted a reply but before local acknowledgement may cause the response to be sent again after restart. This is acceptable and must be documented/tested. It must not duplicate inventory mutation.

## Reply rendering

Use plain text.

Split responses longer than the Bot API text limit into deterministic ordered chunks.

Current official Bot API documentation states `sendMessage.text` accepts 1–4096 characters after entity parsing. Keep the limit isolated as adapter configuration/constant and covered by tests rather than scattering it through application code.

## Errors

Classify at adapter boundary:

- unauthorized/non-private/non-text update -> no application call;
- temporary Telegram API failure -> bounded retry/backoff or retry on next loop;
- application clarification -> send ordinary agent text;
- application failure -> safe generic Telegram error without leaking secrets/internal traceback.

## CLI/runtime

Provide an explicit runtime command for the bot process rather than starting a poller as a side effect of the FastAPI web app.

Conceptually:

```text
ah-there-it-is telegram-bot
```

The bot process uses the same database/settings/LLM construction as the web application.

## Testing

Use fake Telegram transport; no live network in CI.

Test at minimum:

- unauthorized user;
- non-private chat;
- non-text update;
- first message creates/reuses mapping;
- second message reuses conversation;
- update replay;
- application mutation replay;
- long response chunking;
- getUpdates transient failure;
- sendMessage transient failure;
- process restart/checkpoint behavior;
- token redaction.

## Telegram photos

Not in first adapter implementation.

Future bridge:

```text
Telegram photo
  -> external media service
  -> provider + media_reference
  -> attach_item_photo(...)
```

This requires no ItemMedia schema change.
