# Core MVP decision — Item photos and Telegram

Status: **accepted** on 2026-09-25.

This decision is intentionally stored on the temporary post-0070 planning branch while implementation batch 0061-0070 is active. Reconcile it against the merged 0070 main before issuing implementation.

It supersedes the earlier classification of photos and Telegram as optional post-MVP work. Both are now required for **core MVP completion**, while preserving the previously accepted single-user architecture.

## Scope boundary

Core MVP must include:

1. inventory-side support for one or more photos associated with an Item through external media references;
2. a working single-user Telegram bot text adapter.

Core MVP still does **not** include:

- image binary storage in the inventory SQLite database;
- vision/image recognition;
- built-in speech-to-text;
- QR/barcodes;
- WhatsApp;
- generic multi-channel/domain abstraction;
- household multi-user/auth/role model.

## Item photos

### Storage model

Inventory stores attachment references and minimal metadata. Media bytes remain external.

Conceptually:

```text
ItemMedia
  id
  item_id
  provider
  media_reference
  caption
  position
  created_at
  updated_at
```

Core MVP supports images only. Do not generalize the domain into arbitrary documents/audio/video merely because the table could do so.

Requirements:

- one Item may have zero, one or many image references;
- `provider` is a small opaque adapter/service identifier;
- `media_reference` is opaque to inventory business logic;
- duplicate attachment of the same provider/reference to the same Item is rejected;
- the same external reference may be associated with another Item when explicitly requested;
- stable Item ID is the association identity on the inventory side;
- caption is optional user-editable text;
- ordering is explicit and deterministic;
- image bytes, thumbnails, external deletion and garbage collection belong to the media service.

### Lifecycle

- Item `removed` does not detach or delete photos.
- Restoring an Item preserves all photo references.
- Removing an Item never calls an external media delete operation.
- Detaching a photo removes only the current association; it does not delete external media.
- Attach, detach, caption change and reorder should create Item Events sufficient for history.
- These association operations may participate in immediate one-level Undo through compensating mutations.

### Split

**Do not automatically copy photo/media references on Item split.**

The source/remainder retains its references. The new child starts with no photo references unless the user explicitly attaches them.

Rationale: a photo can depict the particular physical lot, packaging, damage, serial label or location context. Blind copying would create unsupported identity claims.

This intentionally differs from the accepted free-text comment behavior, where comments are copied and then independently editable.

### Search and AI behavior

Core MVP does not:

- index image contents;
- infer Item facts from images;
- send images to an LLM;
- parse captions into authoritative structured data.

Captions may be displayed with Item details; adding caption text to search is optional and must not alter write-target safety.

### External media service boundary

The inventory core must not depend on one concrete storage implementation.

A future/external media component may upload/store bytes and return:

```text
provider
media_reference
optional caption/metadata
```

The inventory API then attaches that reference to the Item.

The implementation should define a small provider-neutral boundary so an external application can later resolve/fetch media by `provider + media_reference` without schema changes.

Actual external byte-fetch/display integration is allowed but is not required to make inventory attachment persistence correct. Tests use a fake/in-memory media resolver if a resolver protocol is introduced.

### Portable format

Photo references are **external integration state** and are not added to the portable inventory format in this core batch.

Reasons:

- portable format is logical inventory interchange, not complete external-service backup;
- a media reference can be meaningless without its provider/service;
- full SQLite backup preserves the local attachment associations;
- external media backup/lifecycle remains the external service's responsibility.

Do not introduce portable-v4 only for photo references in core MVP.

This policy can be revisited later if a concrete cross-installation media portability requirement appears.

## Telegram bot

### Architecture

Telegram is an adapter, not inventory domain behavior:

```text
Telegram Bot API
  -> single-user Telegram adapter
  -> shared application chat service
  -> existing AgentRunner / request-key idempotency
  -> inventory domain
  -> response
  -> Telegram Bot API
```

The web chat and Telegram adapter should share the same application-level chat execution service rather than duplicating AgentRunner/ChatRequestService orchestration.

### Supported Telegram mode

Core MVP uses **long polling** only.

Do not implement webhooks in the first version.

The official Bot API supports `getUpdates` long polling and documents it as mutually exclusive with webhooks; `update_id`/offset are designed for duplicate/update sequencing. The adapter uses those semantics rather than building its own polling protocol.

### Single-user security

Required configuration:

- bot token;
- one allowed Telegram user ID.

The adapter accepts only:

- messages whose sender ID equals the configured allowed user;
- private-chat text messages in core MVP.

Reject other users/chats before invoking the application.

No User/Role/Channel domain entity is introduced.

The bot token is secret configuration and must never enter traces, Events, receipts or normal logs.

### Conversation mapping

Persist adapter-local mapping from Telegram private chat ID to application `conversation_id`.

This is Telegram adapter state, not a generic channel abstraction.

The first accepted chat message may create the conversation; later messages reuse it.

### Request idempotency

Derive a deterministic application request key from the Telegram update identity, for example:

```text
telegram:<update_id>
```

Do not include bot token or secret data in the key.

A repeated Telegram update must replay the existing application result rather than apply inventory mutations again.

### Polling checkpoint

Persist the last successfully processed/acknowledged update position as adapter state.

Processing order:

1. receive update;
2. validate sender/private text;
3. invoke application using deterministic request key;
4. send/re-send the resulting response;
5. advance durable adapter checkpoint.

A crash must never duplicate inventory mutation because request-key idempotency is authoritative.

Telegram outbound `sendMessage` itself does not provide an application idempotency key. Therefore exact-once reply delivery is not guaranteed across a crash after Telegram accepted the message but before local acknowledgement. Core contract is:

- **exactly-once inventory effect via application request key;**
- **at-least-once best-effort Telegram reply.**

Rare duplicate reply after an uncertain crash boundary is acceptable; duplicate inventory mutation is not.

### Text output

Send plain text in core MVP; do not require Markdown/HTML parse modes.

Telegram currently limits `sendMessage.text` to 1–4096 characters after entity parsing, so the adapter must deterministically split longer responses into ordered chunks.

### Commands

Adapter-only commands may include:

- `/start`;
- `/help`;
- a minimal health/status command if useful.

Inventory changes continue through ordinary natural-language text and existing agent tools. Telegram commands must not duplicate inventory mutation semantics.

### Telegram media

Telegram photo ingestion is **not** part of the first Telegram core adapter.

Photos remain the separate provider/reference mechanism above. A later bridge may convert Telegram photos into external media references without changing ItemMedia schema.

## Testing boundary

Telegram tests must not call the live Telegram network.

Use a fake Bot API transport to test:

- update validation;
- allowed-user enforcement;
- private-chat enforcement;
- polling offset/checkpoint behavior;
- deterministic request keys;
- conversation reuse;
- duplicate update replay;
- response chunking;
- transient send/getUpdates failures;
- crash/restart behavior around the application commit boundary.

Live Telegram smoke testing is optional/manual and must never be a normal CI requirement.

## Core MVP implication

Core MVP is not declared complete immediately after 0061-0070.

After that batch, the planned core sequence is:

1. reconcile this decision with merged 0070;
2. implement Item media references + Telegram adapter;
3. final correctness audit/fixes;
4. complete provider/model evaluation/promotion tooling;
5. declare core MVP complete.
