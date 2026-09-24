# Session handoff

## Current state

Repository: `buzlet/ah-there-it-is`.

Product stages through Stage 26 and assignments through 0040 are complete.

Active implementation protocol:

`agent-tasks/common/v8.md`

Historical process material is archived and is not normal implementation context.

## Execution

Direct U24 execution runs as OS user `rdu01`.

Each issued patch/batch receives its own exact checkout path under:

`/home/rdu01/projects/<patch-name>`

The agent must stay inside that checkout for Git, edits, Python, Just and tests. Do not switch to `gpt`, do not use sudo, and do not reuse another patch checkout.

The direct-shell environment is already connected to U24.

Remote Commander on U24 remains available when explicitly selected.

Python 3.12 is the only required CI/test compatibility target. Do not add Python 3.13+ verification lanes without an explicit future decision.

## Verification model

One coherent issued batch:

- one implementation branch;
- focused checkpoint per task;
- no full repository suite between tasks;
- one final PR;
- one authoritative full CI;
- full local regression only when manifest sets `full_local_required: true`.

## Useful process tools

- `tools/agent/lifecycle_checkpoints.py`;
- `tools/agent/canonical_verifier.py` for manifest-declared full-local runs;
- `tools/agent/ci_waiter.py`.

## Product summary

Current system includes nested inventory trees, deterministic search, explicit location truth, sold/discarded lifecycle + reactivation, historical Event path evidence, provider-neutral scenarios, write-target safety, atomic turns/receipts, crash-safe idempotency, bounded conversation context, doctor/FTS repair, backup/restore/rehearsal and portable-v2.

## Next decision

Quantity / physical-instance semantics remain unresolved. Do not implement partial quantity moves/sales/disposal or Item split/merge until explicitly decided.

See `agent-tasks/designs/future-decision-gates.md`.
