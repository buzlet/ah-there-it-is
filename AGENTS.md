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

`sold` and `discarded` are the current runtime terminal states. The accepted next quantity/lifecycle implementation replaces them with one generic `removed` terminal state plus textual removal reason; historical sold/discarded Events remain evidence during migration.

### Quantity / physical instances

Accepted product semantics are defined in:

`agent-tasks/designs/quantity-physical-instance-decision.md`

Key direction:

- Item is a homogeneous physical lot and may represent one object or interchangeable units;
- quantity precision is exact / approximate / unknown and zero is never stored;
- one semantic quantity-change operation may change both value and precision while preserving original text and explicit/context reason;
- partial high-level operations split internally and atomically while the source/remainder keeps its stable ID and the separated lot receives a new stable ID;
- quantity ambiguity normally does not block a safe operation; uncertainty may degrade to unknown and be shown/refined afterwards;
- equivalent lots are allowed but accidental duplicate creation remains guarded by service policy;
- Item merge is not implemented;
- the future terminal lifecycle is one generic `removed` state with textual reason, requiring user intent rather than arithmetic inference;
- split copies the free-text description/comment, which remains user-editable and is not structured measurement truth;
- portable export advances to v3 while frozen v1/v2 imports map integer quantities to exact.

The quantity/physical-instance product-semantic gate is closed. Use the decision document as implementation authority.

### Language and search

The only supported natural language is Russian.

Latin-script product names, model numbers, brand names and technical identifiers are ordinary data, not multilingual support.

Retrieval is deterministic and bounded. Do not add multilingual normalization, language detection, transliteration, cross-language behavior, morphology, fuzzy matching or embeddings without measured Russian-language retrieval failures that justify the specific change.

### Recovery

Full SQLite backup/restore is separate from portable inventory import. Current runtime portable format is v2 with frozen v1 import support; the accepted quantity implementation advances export to v3 while retaining v1/v2 import compatibility. Bootstrap is separate onboarding. Doctor is read-only except explicit derived FTS repair.

Backup scheduling, retention and off-machine copying are external infrastructure and are not application features.

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

## Product/deployment scope

Accepted scope is recorded in:

`agent-tasks/designs/product-scope-decisions.md`

Key rules:

- single logical user only; no household/multi-user account model;
- external surfaces may attach simple source identity/user labels as metadata, without a first-class Channel domain abstraction;
- trace retention/purge management is external; traces are retained for replay/evaluation/model improvement;
- voice recognition is external and the application receives text;
- QR/barcodes are out of scope;
- Telegram bot is an optional future single-user text transport whose account security lives in its adapter/infrastructure;
- future Item photos may be represented by one-or-many external media references;
- provider/model evaluation is a separate subsystem, not inventory-domain behavior;
- WhatsApp and other hypothetical transports are not designed now.

## Current status

Product work through Stage 26 and assignments through 0060 are complete.

Batch 0051–0060 closed bounded portable import/database validation and aligned lifecycle tooling with the integrated-batch v8 manifest/checkpoint model.

### Correction / Undo

Accepted correction/Undo semantics are defined in:

`agent-tasks/designs/undo-correction-decision.md`

Key rules:

- normal corrections are compensating mutations/Events, not history rewrites;
- one-level Undo is desirable only for the immediately preceding committed user mutation action;
- no redo and no arbitrary older undo;
- Undo is compensating and must fail closed if the expected post-state no longer matches;
- split-created equivalent lots do not merge during Undo; the child may simply be moved/restored back and remain separate;
- partial compensation is forbidden;
- Undo does not introduce generic hard delete/purge.

## Next product step

All required product-semantic gates for core MVP are closed.

Next: prepare and issue implementation batches from the accepted design documents, beginning with:

`agent-tasks/designs/quantity-physical-instance-decision.md`

and incorporating the narrow immediate-Undo contract where implementation ordering makes sense.

Do not reopen merge, Product/SKU, continuous-measurement, multi-user, multilingual, QR/barcode, built-in voice, backup-policy, trace-purge or generic hard-delete scope unless a new explicit product decision does so.
