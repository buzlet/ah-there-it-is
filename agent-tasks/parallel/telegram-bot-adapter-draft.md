# Single-user Telegram bot adapter draft

Status: optional post-MVP design draft. Not implementation authority.

## Goal

Expose the existing text inventory interaction through one Telegram bot bound to one allowed Telegram account, without introducing Telegram-specific semantics into the inventory domain.

## Architecture

```text
Telegram update
  -> bot adapter validates allowed sender
  -> normalize incoming text
  -> call existing application chat boundary
  -> receive structured/text response
  -> Telegram reply
```

The inventory application remains single-user.

## Security boundary

The adapter/infrastructure owns:

- bot token;
- allowed Telegram user/account ID;
- Telegram update authentication/transport;
- rejection of messages from other users;
- polling/webhook operational configuration.

Inventory domain does not own Telegram ACLs.

## Conversation mapping

The adapter needs a durable way to map Telegram chat/dialog context to an application `conversation_id`.

For a single-user bot, the simplest policy is one configured application conversation per Telegram chat, with the mapping stored by the adapter.

Do not create a general User/Channel domain model solely for this.

## Idempotency

Telegram update/message identifiers should be mapped to the application's existing request-key/idempotency boundary so replayed updates do not duplicate mutations.

A deterministic adapter request key is preferable to ad-hoc retry detection.

## Input/output scope

Initial adapter should support text only.

Voice notes, photos and documents may be handled by separate upstream processing later:

- voice -> external speech-to-text -> ordinary text;
- photo -> future media service/reference flow.

The bot should not duplicate agent/domain logic.

## Error behavior

The adapter should distinguish:

- temporary infrastructure/provider failure: retry according to Telegram transport policy while preserving request idempotency;
- application ambiguity/clarification: send the agent's normal response;
- unauthorized sender: reject before application invocation.

## No Telegram-specific domain commands

Commands such as `/start`, `/help` or adapter diagnostics may exist at the bot layer, but inventory mutations should continue to flow through natural text/application tools.

## Later implementation dependency

Implement only after core MVP correctness is accepted. It should require little or no change to inventory domain code; any large domain change would indicate a transport-boundary leak.
