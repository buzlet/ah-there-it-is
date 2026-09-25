# 0080 — media/Telegram core integration and review

Status: draft task spec; reconcile after 0061-0070 merge.

## Objective

Close the media + Telegram core batch with a cross-surface audit and runtime/documentation integration.

## Audit

Verify:

- no image bytes in SQLite;
- no vision/image inference;
- photo refs stay attached across removed/restore;
- split-no-copy invariant;
- no portable-v3 semantic change;
- no Telegram types/imports in inventory domain;
- no User/Channel/role model;
- Web and Telegram share one chat execution/idempotency path;
- Telegram private single-user restriction;
- request replay cannot duplicate mutation;
- token never appears in traces/Events/receipts/errors.

## Runtime/docs

Update:

- Settings/.env example;
- runtime CLI help;
- Item media API/docs;
- Telegram bot startup/config docs;
- core MVP task/status docs.

Do not claim Telegram webhook/group/photo support.

## Verification when issued

Because this batch contains migrations, external-adapter runtime and shared chat/idempotency refactoring, issue it with full_local_required: true.

One final integration set, one full-local v8 gate, one PR, authoritative exact-head CI.
