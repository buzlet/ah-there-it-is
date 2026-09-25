# 0077 — Telegram idempotency and polling state machine

Status: draft task spec; reconcile after 0061-0070 merge.

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
