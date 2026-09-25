# 0085 — Crash, idempotency and recovery hardening

## Objective

Fault-inject the integrated keyed request and Telegram polling paths. Preserve fail-closed inventory semantics while ensuring every supported recovery path is explicit and testable.

## Required work

Exercise at least:

- crash/exception after request-key reservation but before AgentRunner work;
- failure after provisional mutation work but before final commit;
- final-commit uncertainty before vs after durable commit;
- lost caller response after completed commit;
- replay of completed/failed/processing keys;
- explicit operator recovery to a distinct request key;
- Telegram mutation committed but send fails;
- send succeeds but checkpoint/ack is uncertain;
- duplicate/stale/out-of-order update IDs;
- restart from durable polling checkpoint.

Pay special attention to a request record left `processing` by process death after reservation. Do **not** invent TTL/automatic retry. Confirm the existing explicit recovery contract is safe and observable; fix code-level defects only if a reproducible path can duplicate mutation, lose an accepted update, or make the documented recovery contract unusable.

Test accidental concurrent workers enough to determine whether the problem is code-level or deployment-level. If safe resolution requires guaranteeing a single target-host service instance rather than an application change, record:

`DIRECT FOLLOW-UP: ...`

with the exact requirement/test for the later Direct batch. Do not add a distributed lease speculatively.

## Focused verification

    .venv/bin/python -m pytest -q       tests/test_idempotency.py       tests/test_idempotency_crash.py       tests/test_chat_application_service.py       tests/test_telegram_adapter.py       tests/test_telegram_runtime.py       tests/test_media_telegram_integration.py       tests/test_atomic_turn_receipts.py
    make compile
    git diff --check
