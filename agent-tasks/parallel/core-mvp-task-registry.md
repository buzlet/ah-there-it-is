# Core MVP task registry after active batch 0061-0070

Status: planning/reservation only. Do not issue as immutable control until 0061-0070 is merged and this branch is reconciled.

## Active now

0061-0070 — quantity / removed / portable-v3 / immediate Undo.

Owned by the currently running implementation agent.

## Reserved next core batch: 0071-0080

Purpose: Item photo references + single-user Telegram bot, then integration closure.

### 0071 — ItemMedia schema and migration

- add ItemMedia association table;
- provider/reference/caption/position/timestamps;
- constraints/indexes;
- no image bytes;
- removed Items retain media;
- installed-wheel/fresh/upgrade migration tests.

### 0072 — Item photo domain service and history

- attach/list/update/detach;
- stable Item write resolution;
- deterministic ordering;
- structured attach/update/detach Events;
- no external byte deletion;
- split child receives no copied media.

### 0073 — photo API, web projection and immediate Undo

- structured REST/manual-web surfaces;
- Item detail lists photo refs/captions;
- optional resolver seam with fake implementation;
- one-level Undo for attach/detach/caption/order mutations;
- no vision or image-content search;
- portable-v3 explicitly remains unchanged.

### 0074 — shared application chat execution boundary

- extract web-route chat orchestration into reusable application service;
- preserve ChatRequestService request-key/idempotency semantics;
- preserve AgentRunner transaction behavior/receipts;
- web API behavior remains compatible;
- no Telegram code in inventory domain.

### 0075 — Telegram Bot API client

- httpx-based provider-neutral-ish Telegram transport wrapper;
- getUpdates long polling;
- sendMessage;
- plain-text deterministic chunking;
- bounded timeout/retry/backoff;
- no additional Telegram dependency;
- secret-safe errors/logging;
- fake transport tests.

### 0076 — Telegram single-user authorization and conversation mapping

- required bot token + allowed user ID settings;
- private-chat text only;
- reject unauthorized/non-private/non-text before app call;
- persist Telegram chat -> application conversation mapping;
- no generic User/Channel model.

### 0077 — Telegram update idempotency and checkpoint state machine

- request_key = telegram:<update_id>;
- durable polling checkpoint;
- repeated Update replays result, never mutation;
- crash/restart tests;
- document/accept at-least-once outbound reply at uncertain send acknowledgement boundary.

### 0078 — Telegram runtime command and operational behavior

- explicit `ah-there-it-is telegram-bot` process;
- no FastAPI startup side effect;
- graceful bounded polling loop;
- application/provider configuration reuse;
- /start and /help adapter-only commands if useful;
- health/error behavior without secret leakage.

### 0079 — media + Telegram integrated scenarios/hardening

- target-scale ItemMedia associations;
- removed/restore + photos;
- split-no-copy invariant;
- Undo media association mutations;
- Telegram duplicate/retry/idempotency;
- long text responses;
- failure injection;
- package/runtime tests.

### 0080 — core media/Telegram integration review

- cumulative API/UI/runtime/history audit;
- verify no Telegram concepts leaked into inventory domain;
- verify no image bytes/vision accidentally entered core;
- docs/config examples;
- one full-local v8 verification when issued;
- final PR/CI.

## After 0080, still core before MVP declaration

1. final correctness audit against merged 0061-0080 runtime;
2. fix only concrete audit findings;
3. provider/model evaluation promotion tooling based on the existing evaluation stack and `provider-evaluation-gap-audit.md`;
4. final MVP acceptance.

## Not core implementation

- executor/process redesign;
- Telegram webhooks;
- Telegram group support;
- Telegram photo ingestion;
- external media storage service itself;
- image vision/recognition;
- WhatsApp;
- QR/barcodes;
- voice recognition;
- multi-user;
- multilingual search;
- backup scheduling;
- trace purge.
