# 0079 — media and Telegram integration hardening

Status: issued implementation spec for batch 0071–0080.

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


## Issued hardening constraints

Add deterministic structural tests, not wall-clock performance thresholds.

Create `tests/test_media_telegram_integration.py`.

Target-scale/media cases must include many Items with multiple associations and duplicate/equivalent lots without weakening stable-ID mutation safety.

Telegram failure injection must cover repeated updates and the commit/send/checkpoint crash boundaries from 0077.

No live Telegram network and no external media service are allowed in CI.

## Focused verification

Run exactly:

    .venv/bin/python -m pytest -q tests/test_media_telegram_integration.py tests/test_item_media.py tests/test_telegram_client.py tests/test_telegram_adapter.py tests/test_target_scale.py tests/test_undo.py tests/test_idempotency.py tests/test_idempotency_crash.py tests/test_write_target_safety.py -k "media or photo or telegram or duplicate or equivalent or undo or replay or crash or target"
    make compile
    git diff --check
