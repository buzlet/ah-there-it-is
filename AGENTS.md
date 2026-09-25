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

`removed` is the runtime terminal state and carries a textual removal reason. Historical sold/discarded Events remain evidence after migration.

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
- the terminal lifecycle is one generic `removed` state with textual reason, requiring user intent rather than arithmetic inference;
- split copies the free-text description/comment, which remains user-editable and is not structured measurement truth;
- portable export advances to v3 while frozen v1/v2 imports map integer quantities to exact.

The quantity/physical-instance product-semantic gate is closed. Use the decision document as implementation authority.

### Language and search

The only supported natural language is Russian.

Latin-script product names, model numbers, brand names and technical identifiers are ordinary data, not multilingual support.

Retrieval is deterministic and bounded. Do not add multilingual normalization, language detection, transliteration, cross-language behavior, morphology, fuzzy matching or embeddings without measured Russian-language retrieval failures that justify the specific change.

### Recovery

Full SQLite backup/restore is separate from portable inventory import. Current runtime portable format is v3 with frozen v1/v2 import compatibility. Bootstrap is separate onboarding. Doctor is read-only except explicit derived FTS repair.

Backup scheduling, retention and off-machine copying are external infrastructure and are not application features.

## Active implementation protocol

For batches issued after the v9 process change, use:

`agent-tasks/common/v9.md`

Each issued task is one file committed to `main`. The commit containing the
finalized task file is its immutable issuance SHA.

Task and executor are separate issuance inputs. The task never embeds environment
details or selects its executor.

There is no control branch, seed, assignment copy, committed self-review file or
separate reviewer-correction PR in v9.

Do not migrate an already-running v8 batch to v9 mid-execution.

Do not run repository-wide regression after each task. Verification breadth and
`full_local_required` come from the issued batch file.

## Execution

Execution-environment details are not duplicated in batch specifications.

At issuance the orchestrator supplies a separate executor path, for example:

`Executor: agent-tasks/executors/chatgpt-sandbox.md`

Available executor profiles live under `agent-tasks/executors/`.

The selected executor profile owns user/workdir/bootstrap/network/publication and
host-specific stop rules. The task file contains none of those details.

Windows Git Bash remains pending native validation and may be selected only when
its executor profile explicitly permits the issued work.

### Python verification policy

Python 3.12 is the project CI/test compatibility target. Do not add Python 3.13 or later-version CI matrices, smoke jobs, or compatibility pilots unless an explicit future project decision changes this policy. The package metadata may remain forward-compatible; lack of a newer-version CI lane is intentional and is not a missing verification requirement.

## Default reading

Read only:

1. this file;
2. the issued task file at the issuance SHA;
3. the separately supplied executor profile at the same issuance SHA;
4. `agent-tasks/common/v9.md`;
5. relevant source/tests.

Do not recursively read `agent-tasks/archive/`.

## Process helpers

- `tools/agent/canonical_verifier.py` — optional when the issued batch explicitly requires durable full-local verification;
- `tools/agent/ci_waiter.py` — optional bounded exact-head CI observer where its environment supports it;
- v8 lifecycle/seed helpers are legacy and are not used by new v9 batches.

## Product/deployment scope

Accepted scope is recorded in:

`agent-tasks/designs/product-scope-decisions.md`

Key rules:

- single logical user only; no household/multi-user account model;
- external surfaces may attach simple source identity/user labels as metadata, without a first-class Channel domain abstraction;
- trace retention/purge management is external; traces are retained for replay/evaluation/model improvement;
- voice recognition is external and the application receives text;
- QR/barcodes are out of scope;
- a single-user Telegram bot text adapter is required before core MVP completion; its account security lives in its adapter/infrastructure;
- Item photo support is required before core MVP completion and uses one-or-many external media references without storing image bytes in inventory SQLite;
- provider/model evaluation is a separate subsystem, not inventory-domain behavior;
- WhatsApp and other hypothetical transports are not designed now.

## Current status

Product work through Stage 26 and assignments through 0083 is complete.

Batches 0071–0080 and 0081–0083 implemented Item media references, the single-user/private-text Telegram adapter, and provider/model benchmark-promotion tooling. Independent post-merge reviews produced corrective PRs #84 and #83; both corrections are merged into current main.

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

All required product-semantic gates for the implemented core are closed.

Next is one sandbox-only final MVP correctness/hardening batch (0084–0090). It may add regression tests and narrow code corrections only; it must not add new product scope or prepare the deployment host.

After independent review/corrections of that batch, deployment/environment readiness is a separate Direct-shell batch on the actual target server. That Direct work owns service-manager setup, filesystem/env/secrets layout, deployment rehearsal, operational paths and other host-specific readiness.

Do not reopen merge, Product/SKU, continuous-measurement, multi-user, multilingual,
QR/barcode, built-in voice, backup-policy, trace-purge or generic hard-delete
scope unless a new explicit product decision does so.
