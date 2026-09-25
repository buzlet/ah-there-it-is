# Batch manifest: core Item photos + Telegram 0071–0080

Batch ID: post-0070-media-telegram-core-2026-09-25

Protocol: agent-tasks/common/v8.md

Expected start main:

153435ef3272a134d85ff02bcc370b8121b0708a

Implementation branch:

feat/core-media-telegram-0071-0080

Execution:
- host_profile: u24-bash
- execution_channel: direct-shell
- execution_user: rdu01
- workdir: /home/rdu01/projects/core-media-telegram-0071-0080

Batch review destination:

agent-tasks/reviews/0071-0080-media-telegram-core-r1.md

Full local regression:

full_local_required: true

## Authoritative product decisions

Implement exactly:

- agent-tasks/designs/media-telegram-core-decision.md
- agent-tasks/designs/media-reference-contract.md
- agent-tasks/designs/telegram-bot-adapter.md
- agent-tasks/designs/product-scope-decisions.md
- agent-tasks/designs/undo-correction-decision.md

Do not reopen these decisions.

## Objective

Complete the remaining media/Telegram core-MVP implementation:

1. Item photo-reference persistence without image bytes;
2. inventory photo service/history and split/lifecycle semantics;
3. Web/agent/Undo photo association surfaces;
4. one shared application chat execution boundary;
5. narrow Telegram Bot API long-poll transport;
6. strict single-user/private-text Telegram adapter state;
7. request-key/checkpoint crash-safe polling behavior;
8. explicit Telegram runtime command;
9. media/Telegram scale, idempotency, security and failure hardening;
10. integrated runtime/documentation closure.

## Ordered tasks

1. 0071 — ItemMedia schema and migration
2. 0072 — Item photo domain service and history
3. 0073 — Item photo agent/web surfaces and Undo
4. 0074 — shared chat execution service and source identity
5. 0075 — Telegram Bot API client
6. 0076 — Telegram single-user security and adapter state
7. 0077 — Telegram idempotency and polling state machine
8. 0078 — Telegram runtime command and operational loop
9. 0079 — media and Telegram integration hardening
10. 0080 — media/Telegram core integration and review

Exact task specs:
- agent-tasks/batches/post-0070-media-telegram-core/0071-item-media-schema.md
- agent-tasks/batches/post-0070-media-telegram-core/0072-item-photo-domain-history.md
- agent-tasks/batches/post-0070-media-telegram-core/0073-item-photo-agent-web-undo.md
- agent-tasks/batches/post-0070-media-telegram-core/0074-shared-chat-service-source-identity.md
- agent-tasks/batches/post-0070-media-telegram-core/0075-telegram-bot-api-client.md
- agent-tasks/batches/post-0070-media-telegram-core/0076-telegram-single-user-state.md
- agent-tasks/batches/post-0070-media-telegram-core/0077-telegram-idempotency-polling.md
- agent-tasks/batches/post-0070-media-telegram-core/0078-telegram-runtime-command.md
- agent-tasks/batches/post-0070-media-telegram-core/0079-media-telegram-hardening.md
- agent-tasks/batches/post-0070-media-telegram-core/0080-media-telegram-core-integration.md

Seed destinations:
- agent-tasks/assignments/0071-item-media-schema.md
- agent-tasks/assignments/0072-item-photo-domain-history.md
- agent-tasks/assignments/0073-item-photo-agent-web-undo.md
- agent-tasks/assignments/0074-shared-chat-service-source-identity.md
- agent-tasks/assignments/0075-telegram-bot-api-client.md
- agent-tasks/assignments/0076-telegram-single-user-state.md
- agent-tasks/assignments/0077-telegram-idempotency-polling.md
- agent-tasks/assignments/0078-telegram-runtime-command.md
- agent-tasks/assignments/0079-media-telegram-hardening.md
- agent-tasks/assignments/0080-media-telegram-core-integration.md

The one batch seed commit must contain this manifest at its active path and exact
byte copies of all ten task specs at the assignment destinations above.

## Sibling parallel batch

Batch 0081–0083 is intentionally issued from the same start-main SHA and owns
provider/model evaluation campaign tooling only.

An origin/main advance caused **solely** by merge of the issued sibling
0081–0083 batch is explicitly authorized and is not a v8 stop condition.

If that happens:

- do not rebase or merge sibling commits into this task history mid-batch;
- continue from the issued start-main;
- before final merge require the PR to be conflict-free against current main;
- authoritative exact-head PR CI must run against current main;
- stop if the sibling changed files owned by this batch or if main advanced for
  any unrelated reason.

## File/scope ownership

This batch owns media persistence/service/API/agent/Undo, shared chat application
boundary, Telegram adapter/runtime, their migrations/tests and final core status
documentation.

It must not implement the sibling model-evaluation campaign/report modules.

## Dependency/network policy

- use existing dependencies; Telegram transport uses httpx;
- no Telegram SDK dependency;
- no live Telegram network in tests/CI;
- no external media service dependency;
- no provider/model live call added to ordinary CI.

## Final integration

After 0080, before the one full-local gate:

    .venv/bin/python -m pytest -q       tests/test_item_media.py       tests/test_chat_application_service.py       tests/test_telegram_client.py       tests/test_telegram_adapter.py       tests/test_telegram_runtime.py       tests/test_media_telegram_integration.py       tests/test_app.py       tests/test_agent.py       tests/test_undo.py       tests/test_atomic_turn_receipts.py       tests/test_idempotency.py       tests/test_idempotency_crash.py       tests/test_write_target_safety.py       tests/test_migrations.py       tests/test_wheel_migrations.py       tests/test_runtime_cli.py       tests/test_trace_config_privacy.py
    make provider-contract
    make compile
    git diff --check

Then run the v8 full-local sequence exactly once:

    make check
    make migration-check
    make corpus-check
    make scenario-check
    make scenario-eval
    make retrieval-eval

Do not run the full-local sequence after individual tasks.

## Stop conditions

Stop rather than weaken the contract if implementation would require:

- image bytes in inventory SQLite;
- vision/image fact inference;
- copying source Item photos automatically onto split children;
- portable-v4 solely for media references;
- Telegram webhook/group/photo ingestion;
- general User/Channel/Role domain architecture;
- Telegram mutation without the existing request-key idempotency boundary;
- storing/logging the bot token;
- live Telegram network in tests;
- a new Telegram SDK/dependency;
- provider/model evaluation work owned by sibling 0081–0083;
- bypassing stable-ID/write-target safety;
- weakening immediate Undo/history semantics.

## Final lifecycle

After 0080:
- cumulative seed..HEAD self-review;
- one pre-PR batch review;
- final integration checks;
- one full-local v8 gate;
- one PR;
- authoritative exact-head CI;
- narrow correction loop only if required;
- merge commit after green exact head;
- clean main sync;
- seed ancestry proof;
- compact completion report.
