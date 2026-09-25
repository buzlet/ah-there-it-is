# Product scope decisions after quantity gate

Status: accepted product direction on 2026-09-25.

This document separates core-product responsibilities from infrastructure/adapters and closes several previously listed future decision gates.

## Core deployment model

The application is **single-user**.

There is one logical owner. The same owner may appear through different external surfaces or identities, for example:

- web;
- Telegram;
- a future WhatsApp integration;
- another external text transport.

The domain does not need a first-class Channel abstraction and does not model household/multi-user ownership, permissions, visibility or roles.

When useful for audit/debugging, an external adapter may attach a simple source identity/user label to a request or trace. Such labels are metadata, not authorization identities and not domain ownership.

## Backups

Automated backup scheduling, retention, off-machine copying and encryption policy are **not implemented by this application**.

Backup/restore primitives may remain available, but scheduling/retention/copy policy belongs to external infrastructure.

## Trace retention

Agent traces are retained permanently for future evaluation, replay and model improvement.

The application does not implement trace-retention policy, automatic purge or lifecycle management. Any archival/removal policy is external infrastructure.

Inventory Event history and agent traces remain conceptually separate.

## Authentication, multi-user and remote access

Household/multi-user support is not implemented. The product remains single-user.

The application does not introduce a general account/role/permission model merely to support multiple transports.

Remote access is not a separate domain feature. A concrete external transport or deployment layer is responsible for its own authentication/security boundary.

## Voice

Voice recognition is not implemented.

If voice is used, speech-to-text happens on the user's end device or another external component. The application receives ordinary text through the same text-processing path as typed input.

No voice-specific inventory semantics are introduced.

## Images/photos

Item photo-reference support is required before core MVP completion.

One Item may reference zero, one or multiple externally stored photos.

The core stores only provider/reference associations and minimal metadata. Image bytes, thumbnails, external retention/deletion and vision recognition remain outside inventory persistence.

Accepted detailed semantics are recorded temporarily during the active 0061-0070 batch in:

`agent-tasks/parallel/core-media-telegram-decision.md`

and will be reconciled into normal design context before the media/Telegram implementation batch is issued.

## QR codes and barcodes

QR/barcode support is not implemented and is not on the current roadmap.

## Telegram and external chat transports

A single-user Telegram bot text adapter is required before core MVP completion.

Expected architecture:

```text
Telegram bot
  -> authenticated single-user text adapter
  -> existing application/agent text API
  -> inventory domain
  -> text response
  -> Telegram bot
```

Telegram-specific security/account binding is handled by the Telegram bot/infrastructure, configured for one allowed user/account.

The inventory domain must not acquire Telegram-specific commands or authorization semantics.

The first implementation uses Telegram Bot API long polling, private text messages from one configured allowed Telegram user, the existing application request-key idempotency boundary, and a shared Web/Telegram chat execution service.

Other transports such as WhatsApp are not designed now. The product merely preserves the principle that an external adapter may submit ordinary text to the application.

## Provider/model evaluation

Provider/model choice remains outside inventory-domain architecture.

A separate evaluation substructure is required for comparing providers/models/prompts using captured scenarios, replay and measurable results.

Evaluation should cover, as applicable:

- correct tool selection;
- correct mutation results;
- write-target safety;
- hallucinated facts;
- unnecessary clarification rate;
- handling of quantity uncertainty;
- scenario/corpus success;
- latency;
- tokens/cost;
- repeatability/stability.

Application behavior must not depend on provider-specific quirks. Mock/provider-neutral scenarios remain the primary implementation-development path; real-model promotion is an evaluation/configuration decision.

## Supported natural language

The only supported natural language is **Russian**.

Consequences:

- prompts and clarification behavior are designed for Russian;
- scenario/evaluation corpora primarily use Russian;
- UI/user-facing natural-language messages may be Russian;
- retrieval/search improvements are evaluated against Russian real-world failures;
- no multilingual normalization layer is required;
- no language detection requirement;
- no transliteration feature is required;
- no Ukrainian/Russian or English/Russian semantic-equivalence layer is required;
- cross-language embeddings are not planned.

Latin-script product names, model numbers and technical terms such as `USB-C`, `HDMI`, `ESP32-S3`, brand names and identifiers are normal data and do not constitute multilingual support.

Russian morphology, fuzzy matching or embeddings are not roadmap requirements by default. They may be introduced only if measured retrieval failures justify a concrete change.

## Out of application scope

The following are explicitly outside the application's planned responsibility unless a new explicit decision reopens them:

- backup scheduling/retention/off-machine copy policy;
- trace retention/purge management;
- household multi-user;
- general account/role/permission system;
- built-in voice recognition;
- QR/barcodes;
- multilingual support;
- generic transport abstraction for hypothetical channels.

## Remaining core-MVP implementation areas

After the active quantity/lifecycle/Undo batch, core MVP still requires:

- Item photo/media-reference support;
- single-user Telegram bot text adapter;
- final correctness audit/fixes;
- provider/model evaluation/promotion tooling based on the existing evaluation stack.

## Remaining decision gates

There are no unresolved product-semantic decision gates required for core MVP. Undo/correction and hard-delete/purge semantics are already closed in:

`agent-tasks/designs/undo-correction-decision.md`

The remaining work is implementation and verification.
