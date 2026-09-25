# 0077 — Telegram idempotency and polling state machine

Status: issued implementation spec for batch 0071–0080.

## Objective

Guarantee exactly-once inventory effect for replayed Telegram updates and define restart-safe long-poll processing.

## Request key

For accepted Update N:

    request_key = "telegram:" + str(update_id)

Do not include bot token, chat contents or secret values.

Repeated Update delivery must replay the prior application result and must not create another inventory mutation.

## Processing state machine

1. get update;
2. validate allowed private-text sender;
3. resolve/reuse application conversation;
4. execute shared chat service with deterministic request key/source_identity;
5. send response;
6. advance durable adapter checkpoint.

Use Bot API offset semantics consistently with the persisted checkpoint.

## Delivery guarantee

- inventory effect: exactly once through existing request-key semantics;
- outbound Telegram reply: best-effort at least once.

Document/test the unavoidable uncertain boundary: crash after Telegram accepted sendMessage but before local acknowledgement may duplicate the reply after restart, but never the inventory mutation.

## Failure injection

Cover crashes/failures:

- before application call;
- after app commit before send;
- after send before checkpoint;
- before/after checkpoint;
- repeated getUpdates response.


## Issued state-machine constraints

- Process updates in deterministic update_id order.
- request_key is exactly `telegram:<update_id>`.
- An unauthorized/non-text update performs no application call but advances the durable offset after safe discard.
- If application commit succeeds and sendMessage fails, do not advance the update checkpoint; replay must reuse the already committed application result and retry delivery.
- If sendMessage succeeds but checkpoint persistence is uncertain, duplicate reply on replay is acceptable.
- Inventory mutation duplication is never acceptable.
- No attempt to manufacture exactly-once Telegram outbound delivery.

## Focused verification

Use `tests/test_telegram_adapter.py` plus existing idempotency/crash suites.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_telegram_adapter.py tests/test_idempotency.py tests/test_idempotency_crash.py -k "telegram or replay or checkpoint or offset or idempotency or crash"
    make compile
    git diff --check
