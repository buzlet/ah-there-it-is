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

Future photo support is desirable.

One Item may eventually reference one or more photos/images.

Image bytes do not need to live in the core SQLite database. A future external media application/service may store images and return references in a defined request/response contract.

The inventory application should eventually need only enough structured metadata to associate media references with an Item. Vision recognition, image understanding and media storage are separate concerns and are not part of the current core implementation.

The exact media-reference contract is future implementation design, not a blocker for the current core MVP.

## QR codes and barcodes

QR/barcode support is not implemented and is not on the current roadmap.

## Telegram and external chat transports

A Telegram bot is a desirable optional transport after core MVP.

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

## Future optional implementation areas

The following remain valid future work but do not block core MVP:

- Telegram bot adapter;
- Item photo/media-reference support;
- provider/model evaluation tooling and reports.

## Remaining decision gates

This document does not decide generic Undo/correction UX or destructive hard-delete/purge semantics. Those remain separate questions in `agent-tasks/designs/future-decision-gates.md`.

Neither is required merely to implement the already-accepted quantity/physical-instance model.
