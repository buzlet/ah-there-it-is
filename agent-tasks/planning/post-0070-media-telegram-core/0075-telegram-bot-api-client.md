# 0075 — Telegram Bot API client

Status: draft task spec; reconcile after 0061-0070 merge.

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
