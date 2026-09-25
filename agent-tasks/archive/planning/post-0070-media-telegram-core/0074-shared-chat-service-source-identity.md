# 0074 — shared chat execution service and source identity

Status: draft task spec; reconcile after 0061-0070 merge.

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
