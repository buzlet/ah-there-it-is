# 0084 — Integrated chat transaction and cross-surface invariants

## Objective

Independently audit the integrated Web / Agent / Telegram chat path after all reviewed corrections. Reproduce and fix only concrete code-level violations of existing transaction, idempotency, receipt and write-target invariants.

## Required work

- Trace Web and Telegram entrypoints through `ChatApplicationService`, `ChatRequestService`, `AgentRunner`, tool dispatch and inventory services.
- Verify no adapter/route owns a second mutation pipeline or writes inventory state directly.
- Verify successful mutation turns expose backend-owned receipts and failed turns leave no partial inventory/Event/message mutation.
- Re-test a **failed first turn on a newly created conversation**. Record exactly which Conversation, Message, AgentRunLog and ChatRequest rows survive.
  - Do not invent new product semantics.
  - If an empty Conversation is user-visible or violates an existing atomicity/audit contract, reproduce with a regression test and make the narrowest correction that preserves failed-run evidence.
  - If the row is intentionally required as an audit/FK anchor and is not user-visible, keep it and add evidence/regression coverage rather than deleting history.
- Verify request-key replay behavior is identical regardless of Web/Telegram caller.
- Verify source identity remains audit metadata only and cannot authorize a write.

## Non-goals

No new transport abstraction, multi-user model, UI redesign, or deployment-host work.

## Focused verification

    .venv/bin/python -m pytest -q       tests/test_chat_application_service.py       tests/test_agent.py       tests/test_app.py       tests/test_atomic_turn_receipts.py       tests/test_write_target_safety.py       tests/test_idempotency.py
    make compile
    git diff --check
