# Session handoff

## Current state

Repository: `buzlet/ah-there-it-is`.

Product stages through Stage 26 and assignments through 0034 are complete.

Active implementation protocol:

`agent-tasks/common/v8.md`

Historical process material is archived and is not normal implementation context.

## Execution

Established U24 account:

- user: `gpt`;
- home: `/home/gpt`;
- repo: `/home/gpt/projects/ah-there-it-is`;
- venv: repository `.venv`.

The direct-shell environment is already connected to U24. Do not create an SSH layer or launch a nested Codex process.

Remote Commander on U24 remains available when explicitly selected.

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
