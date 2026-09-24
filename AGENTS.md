# AGENTS.md

## Purpose

Current architecture and implementation rules for `buzlet/ah-there-it-is`.

Default agent context is intentionally small.

## Product

Local-first personal inventory memory for roughly 100–250 nested Locations and about 1000 Items.

## Architecture invariants

- SQLite + SQLAlchemy are authoritative persistence.
- Service/domain code owns writes, invariants, transactions and Event history.
- The LLM never writes the database directly.
- Stable IDs are preserved.
- Startup never auto-migrates or auto-repairs.
- Search ranking never authorizes writes.
- Existing mutation targets require strong identity evidence and atomic revalidation.
- Agent turns are transactionally atomic.
- Failed mutation turns roll back.
- Successful changes expose backend-owned mutation receipts.
- Request-key idempotency owns crash-safe retries.

### Location truth

`location_status` is authoritative:

- `known` → current Location exists;
- `unknown` → whereabouts unknown;
- `in_use` → intentionally outside storage;
- `not_applicable` → terminal Item.

`sold` and `discarded` are terminal. Move/take/location-unknown/sold/discard/reactivation are explicit operations.

### Search

Retrieval is deterministic and bounded. Fuzzy matching, transliteration, morphology and embeddings remain deferred pending measured need.

### Recovery

Full SQLite backup/restore is separate from portable inventory import. Current portable format is v2 with frozen v1 import support. Bootstrap is separate onboarding. Doctor is read-only except explicit derived FTS repair.

## Active implementation protocol

Use only:

`agent-tasks/common/v8.md`

One issued batch has one implementation branch, focused checkpoint per task, one final PR and one authoritative full CI.

Do not run repository-wide regression after each task.

Full local regression is run only when the immutable manifest says `full_local_required: true`.

The agent must not expand verification scope on its own.

## Execution

Direct U24 execution is already connected to the machine and runs as OS user `rdu01`.

The launcher supplies a unique patch checkout under:

`/home/rdu01/projects/<patch-name>`

All Git, edits, Python, Just and tests must run only inside that exact checkout. Do not switch users, use sudo, or operate in another repository checkout.

Remote Commander on U24 remains supported when explicitly selected.

Windows Git Bash through Remote Commander is prepared but pending native validation.

## Default reading

Read only:

1. this file;
2. exact issued manifest/task specs;
3. `agent-tasks/common/v8.md`;
4. relevant source/tests.

Do not recursively read `agent-tasks/archive/`.

## Process helpers

- `tools/agent/lifecycle_checkpoints.py` — read-only control/seed/checkpoint inspection;
- `tools/agent/canonical_verifier.py` — optional durable full-local verifier for manifest-declared high-risk batches;
- `tools/agent/ci_waiter.py` — bounded exact-head CI observer.


## Current status

Product work through Stage 26 and assignments through 0034 are complete.

## Next product gate

Before partial quantity operations or Item split/merge, explicitly decide the physical-instance/quantity model.

See `agent-tasks/designs/future-decision-gates.md`.


## Direct-shell preflight cadence

For direct U24 batches, verify user/HOME/exact Git toplevel once at batch startup.

Do not repeat that full preflight before each mutation.

Each later independent shell command only needs to `cd` to the launcher-issued workdir (failing if unavailable) and restore the repository-local venv PATH. Repeat the full preflight only after an actual session reset/reconnect or evidence that execution context was lost.
