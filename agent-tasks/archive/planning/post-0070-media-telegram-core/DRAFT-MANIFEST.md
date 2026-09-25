# Draft batch plan: core Item photos + Telegram 0071-0080

Status: DRAFT ONLY. Task IDs are reserved for planning; do not treat this as immutable control.

Prerequisite: implementation batch 0061-0070 merged and main reconciled.

Expected start-main SHA: TBD after 0061-0070.

Implementation branch/workdir/control SHA: TBD when issued.

Full local regression recommendation:

    full_local_required: true

Ordered tasks:

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

Authoritative draft design:

- agent-tasks/designs/media-telegram-core-decision.md
- agent-tasks/designs/media-reference-contract.md
- agent-tasks/designs/telegram-bot-adapter.md

Before issuance:

- diff/reconcile every task against merged 0070;
- update exact focused test commands from the final repository;
- assign start-main/control/implementation execution metadata;
- ensure no overlap with another active checkout;
- move accepted semantics out of temporary parallel docs into normal design/status docs.
