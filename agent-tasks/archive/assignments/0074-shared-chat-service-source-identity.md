# 0074 — shared chat execution service and source identity

Status: issued implementation spec for batch 0071–0080.

## Objective

Extract the current web chat orchestration into one reusable application-level service for Web and Telegram without duplicating AgentRunner/idempotency behavior.

## Shared service

Conceptually:

    execute_chat(message, conversation_id?, request_key?, source_identity?)

It owns/reuses:

- ChatRequestService;
- AgentRunner creation/execution;
- request-key idempotency/replay;
- transaction/failure semantics;
- AgentRunResult/receipts.

Web /api/chat becomes a thin adapter over this service.

## Source identity

Add optional simple source_identity metadata for audit/trace, not authorization.

Examples:

- web;
- telegram:123456789;
- configured human-readable adapter label.

Persist it on the durable request/run boundary where it can be exported/reviewed without introducing User/Channel tables.

Do not let untrusted source_identity alter write authorization.

## Compatibility

- existing Web API behavior remains compatible;
- keyed replay semantics remain identical;
- no Telegram dependency in inventory/domain/agent business modules.


## Issued persistence decision

Persist optional `source_identity` on the durable ChatRequestRecord request boundary.
It is audit/debug metadata only.

- Existing Web calls use a neutral web value or null according to the shared service API.
- Telegram later supplies `telegram:<allowed_user_id>` or a configured non-secret label.
- Replaying an existing request key never overwrites the originally persisted source identity.
- source_identity never grants authorization and is not a User/Channel foreign key.
- Do not duplicate source identity onto AgentRunLog unless a concrete existing reporting API requires it; if duplicated, keep one documented source of truth.

Create a reusable application-level chat execution service. Web `/api/chat` becomes a thin adapter over it.

## Focused verification

Create `tests/test_chat_application_service.py`.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_chat_application_service.py tests/test_app.py tests/test_idempotency.py tests/test_idempotency_crash.py tests/test_evaluation.py tests/test_migrations.py tests/test_wheel_migrations.py -k "chat or request or source_identity or idempotency or migration"
    make migration-check
    make compile
    git diff --check
