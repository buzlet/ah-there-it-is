# 0079 — media and Telegram integration hardening

Status: draft task spec; reconcile after 0061-0070 merge.

## Objective

Exercise the new media and Telegram paths against target-scale, failure, history and security boundaries.

## Media coverage

- many Items with multiple media refs;
- deterministic order;
- duplicate reference constraints;
- removed/restore retention;
- split does not copy refs;
- immediate Undo attach/detach/update;
- external resolver failure cannot corrupt inventory transaction.

## Telegram coverage

- unauthorized user never reaches application;
- private-chat requirement;
- non-text update ignored/rejected;
- conversation mapping reuse;
- update replay;
- request-key crash recovery;
- long response chunking;
- transient getUpdates/sendMessage failures;
- restart/checkpoint cases;
- source_identity persistence;
- token redaction.

## Cross-feature

Do not add Telegram photo ingestion. Verify its absence does not affect text bot operation or ItemMedia API.

No live network or timing thresholds in CI.
