# 0075 — Telegram Bot API client

Status: issued implementation spec for batch 0071–0080.

## Objective

Implement the narrow Telegram HTTP transport using the existing httpx dependency.

## Required Bot API operations

- getUpdates long polling;
- sendMessage.

Do not implement webhooks.

## Client contract

- configurable base URL for tests;
- bot token is injected only into transport URL/auth construction and never emitted in errors/logs/traces;
- bounded connect/read timeout;
- bounded retry/backoff for transient transport/5xx/429-style failures where safe;
- parse only the Update/Message fields needed by the adapter;
- plain-text sendMessage;
- deterministic response splitting using one isolated max-text constant.

Official Bot API currently allows sendMessage text of 1-4096 characters after entity parsing; do not scatter this number through code.

## Tests

Use httpx mock/fake transport. No live Telegram access in normal tests/CI.

Cover malformed API responses, Telegram ok=false responses, transient failures, long polling and chunked sends.


## Issued implementation constraints

- Use the existing httpx dependency; add no Telegram SDK.
- No live Telegram calls in tests or normal CI.
- Keep Bot API parsing intentionally narrow to fields needed by the adapter.
- Isolate the 4096-character sendMessage limit in one adapter constant.
- Token-bearing URLs/exceptions must be sanitized before logging or surfacing.
- Retry/backoff must be bounded; do not implement an unbounded internal loop.

## Focused verification

Create `tests/test_telegram_client.py` using httpx fake/mock transport only.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_telegram_client.py tests/test_trace_config_privacy.py -k "telegram or token or chunk or retry or transport"
    make compile
    git diff --check
