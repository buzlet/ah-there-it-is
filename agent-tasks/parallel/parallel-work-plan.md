# Parallel planning while 0061-0070 is in progress

Status: temporary planning material only. Do not merge into main until batch 0061-0070 is complete and reconciled.

Base main: `fea00581b6f826534cb60d440d14f713da0d9849`.

## Current decision

There are no unresolved core quantity/lifecycle semantics.

Two previously optional integrations are now promoted into **core MVP completion scope**:

- Item photo/media-reference support;
- single-user Telegram bot text adapter.

Accepted design:
`agent-tasks/parallel/core-media-telegram-decision.md`

Reserved implementation plan:
`agent-tasks/parallel/core-mvp-task-registry.md`

Do not issue 0071-0080 until 0061-0070 merges and the specs are reconciled against final code.

## Safe work on this branch

Documentation/design only:

- media-reference contract;
- Telegram adapter contract;
- provider/model evaluation gap audit;
- future batch planning.

No application code is changed here.

## Explicitly out of scope

Executor/process tooling is intentionally left unchanged.

Do not design or implement executor-boundary hardening.

## Work that waits for 0061-0070

- final correctness audit;
- Empty Conversation transaction follow-up;
- evaluation implementation;
- portable/storage follow-up;
- web/manual implementation;
- actual 0071-0080 code.

These overlap the active implementation or need its final interfaces.

## Core sequence

1. finish and merge 0061-0070;
2. reconcile this branch against the resulting main;
3. issue **two independent branches from the same reconciled SHA**:
   - fast lane 0071-0080 — media + Telegram;
   - slow lane 0081-0083 — provider/model evaluation campaign tooling;
4. merge either lane first; keep ownership disjoint;
5. once both are in main, run final correctness audit/fixes;
6. core MVP acceptance.

The fast lane must not depend on any 0081-0083 artifact. The slow lane must not modify media/Telegram/runtime-domain files or project-wide status docs.
