# 0067 — immediate one-level compensating Undo

## Objective

Implement the narrow accepted Undo contract for chat/agent mutation turns using durable receipts/journal evidence, without event rewriting, merge or hard delete.

## Eligibility

Undo targets only the immediately preceding completed user turn in the same conversation.

- If that immediately preceding run has no committed mutations, do not search backward.
- If it is itself an Undo, reject; no redo.
- If any mutation in the logical turn is unsupported for safe compensation, reject the whole Undo.
- Manual/admin mutations outside the AgentRunLog turn boundary are not retroactively guessed as an undo target.

Expose a model-facing undo_last_action operation with no guessed entity IDs. It may be conditionally available when eligibility can be determined safely.

## Fail-closed state verification

Before compensation, verify current affected Item state matches the expected post-state recorded by the previous run.

If any affected state diverged, leave everything unchanged and report Undo unavailable.

## Supported compensation

Support common Item actions when receipts contain sufficient evidence:

- metadata/comment updates;
- semantic quantity changes;
- whole move/location-status transitions;
- take;
- remove;
- restore;
- Item creation where compensation can safely mark the created Item removed rather than hard-delete it;
- partial move/take/remove created through split.

For partial operations:

- do not merge;
- do not restore the source quantity to its pre-split aggregate;
- compensate the child action, e.g. move child back or restore removed child;
- equivalent lots may remain separate.

## Atomicity

A multi-mutation previous turn is Undoable only if the complete turn can be compensated.

Apply compensations in dependency-safe reverse order in one transaction.

No partial compensation.

## History and receipts

- Original Events remain.
- Undo creates compensating Events.
- Record undo_of_run_id in durable receipt/journal evidence.
- The Undo run itself is not a redo target.
- Traces remain permanent.

## Idempotency

A replay of the same keyed Undo request must replay its prior committed result and must not compensate twice.

Crash/failure before commit must leave the original action intact and no partial Undo side effects.

## Focused verification

Create tests/test_undo.py.

    .venv/bin/python -m pytest -q tests/test_undo.py tests/test_atomic_turn_receipts.py tests/test_idempotency.py -k "undo or compensat or receipt"
    just compile
    git diff --check
