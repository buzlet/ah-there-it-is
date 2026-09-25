# 0080 — media/Telegram core integration and review

Status: issued implementation spec for batch 0071–0080.

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


## Issued integration constraints

Update current product/runtime documentation to the implemented truth, including configuration and explicit unsupported Telegram/media capabilities.

The completed batch must leave:

- no active runtime sold/discarded regressions;
- no Telegram imports/types in inventory domain/service modules except neutral application-service interfaces;
- no image bytes/vision implementation;
- no Telegram group/webhook/photo ingestion;
- no generic user/channel/role architecture;
- no portable-v4;
- no provider/model benchmark implementation from sibling batch 0081–0083.

## Focused verification

Run exactly:

    .venv/bin/python -m pytest -q tests/test_item_media.py tests/test_chat_application_service.py tests/test_telegram_client.py tests/test_telegram_adapter.py tests/test_telegram_runtime.py tests/test_media_telegram_integration.py tests/test_app.py tests/test_runtime_cli.py tests/test_activity.py tests/test_migrations.py tests/test_wheel_migrations.py tests/test_undo.py tests/test_idempotency.py tests/test_idempotency_crash.py
    make provider-contract
    make compile
    git diff --check
