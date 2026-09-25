# 0088 — Boundedness, scale and concurrency audit

## Objective

Verify the integrated MVP remains structurally bounded around its intended scale: roughly 100–250 Locations and about 1000 Items plus history/media/chat activity.

## Required work

Prefer deterministic structural/query-count assertions; do not add wall-clock thresholds.

Audit:

- Item/catalog list and page media loading;
- search/result limits;
- conversation context/message windows;
- ChatRequest pagination;
- Event/history reads used by user-facing paths;
- ItemMedia association reads;
- Telegram poll batch size/checkpoint handling;
- duplicate update batches;
- same-key concurrent chat execution;
- concurrent media/lifecycle writes where existing transaction guarantees should reject or serialize safely;
- doctor/diagnostic boundedness.

Re-test obvious N+1 patterns after PR #84.

If concurrent duplicate Telegram processes create only a target-host/service-manager concern, record a precise `DIRECT FOLLOW-UP` rather than introducing deployment architecture in this sandbox batch.

No caching subsystem, distributed queue, worker framework or benchmark-by-time.

## Focused verification

    .venv/bin/python -m pytest -q       tests/test_target_scale.py       tests/test_item_media.py       tests/test_app.py       tests/test_database_doctor.py       tests/test_storage.py       tests/test_idempotency_crash.py       tests/test_telegram_adapter.py       tests/test_media_telegram_integration.py
    make compile
    git diff --check
