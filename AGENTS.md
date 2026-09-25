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

### Quantity / physical instances

Accepted product semantics are defined in:

`agent-tasks/designs/quantity-physical-instance-decision.md`

Key direction:

- Item is a homogeneous physical lot and may represent one object or interchangeable units;
- quantity precision is exact / approximate / unknown;
- partial operations use split while the source/remainder keeps its stable ID;
- the separated lot receives a new stable ID;
- Item merge is not implemented;
- split copies the free-text description/comment, which remains user-editable and is not structured measurement truth.

Do not implement the remaining open quantity questions by inference. Resolve them before issuing the implementation batch.

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

### Python verification policy

Python 3.12 is the project CI/test compatibility target. Do not add Python 3.13 or later-version CI matrices, smoke jobs, or compatibility pilots unless an explicit future project decision changes this policy. The package metadata may remain forward-compatible; lack of a newer-version CI lane is intentional and is not a missing verification requirement.

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

Product work through Stage 26 and assignments through 0060 are complete.

Batch 0051–0060 closed bounded portable import/database validation and aligned lifecycle tooling with the integrated-batch v8 manifest/checkpoint model.

## Next product gate

Quantity/physical-instance direction is accepted, but its implementation batch is not yet ready.

Resolve the open questions listed in:

`agent-tasks/designs/quantity-physical-instance-decision.md`

before implementing quantity precision, partial operations or Item split.
