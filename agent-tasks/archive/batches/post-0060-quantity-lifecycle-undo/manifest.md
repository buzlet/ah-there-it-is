# Batch manifest: quantity lifecycle and immediate Undo 0061–0070

Batch ID: post-0060-quantity-lifecycle-undo-2026-09-25

Protocol: agent-tasks/common/v8.md

Expected start main:

fea00581b6f826534cb60d440d14f713da0d9849

Implementation branch:

feat/quantity-lifecycle-undo-0061-0070

Execution user:

rdu01

Required work directory:

/home/rdu01/projects/quantity-lifecycle-undo-0061-0070

Batch review destination:

agent-tasks/reviews/0061-0070-quantity-lifecycle-undo-r1.md

Full local regression:

full_local_required: true

## Authoritative product decisions

Implement exactly the accepted semantics in:

- agent-tasks/designs/quantity-physical-instance-decision.md
- agent-tasks/designs/undo-correction-decision.md
- agent-tasks/designs/product-scope-decisions.md

Do not reopen those decisions during implementation.

## Objective

Implement the closed quantity/physical-instance product gate as one coherent migration and application change:

1. exact / approximate / unknown quantity truth;
2. homogeneous-lot split semantics and partial high-level operations;
3. generic removed / restore lifecycle and equivalent-lot policy;
4. richer backend receipts and model-facing/web contracts;
5. inventory-portable-v3 with frozen v1/v2 import compatibility;
6. immediate one-level compensating Undo for the previous committed chat mutation turn;
7. Russian-first agent/scenario behavior;
8. scale, atomicity, idempotency and runtime integration hardening.

## Ordered tasks

1. 0061 — quantity and removed schema migration
2. 0062 — semantic quantity value and change operation
3. 0063 — internal split and partial move/take
4. 0064 — removed/restore lifecycle and equivalent lots
5. 0065 — agent/web quantity interfaces and durable receipts
6. 0066 — portable-v3 quantity/lifecycle compatibility
7. 0067 — immediate one-level compensating Undo
8. 0068 — Russian agent scenarios and quantity evaluation
9. 0069 — quantity lifecycle scale/atomicity/idempotency hardening
10. 0070 — quantity lifecycle runtime integration

Exact task specs:
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0061-quantity-removed-schema-migration.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0062-semantic-quantity-change.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0063-split-partial-move-take.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0064-removed-restore-equivalent-lots.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0065-agent-web-quantity-receipts.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0066-portable-v3-quantity-lifecycle.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0067-immediate-one-level-undo.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0068-russian-quantity-scenarios.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0069-quantity-scale-atomicity-idempotency.md
- agent-tasks/batches/post-0060-quantity-lifecycle-undo/0070-quantity-runtime-integration.md

Seed destinations:
- agent-tasks/assignments/0061-quantity-removed-schema-migration.md
- agent-tasks/assignments/0062-semantic-quantity-change.md
- agent-tasks/assignments/0063-split-partial-move-take.md
- agent-tasks/assignments/0064-removed-restore-equivalent-lots.md
- agent-tasks/assignments/0065-agent-web-quantity-receipts.md
- agent-tasks/assignments/0066-portable-v3-quantity-lifecycle.md
- agent-tasks/assignments/0067-immediate-one-level-undo.md
- agent-tasks/assignments/0068-russian-quantity-scenarios.md
- agent-tasks/assignments/0069-quantity-scale-atomicity-idempotency.md
- agent-tasks/assignments/0070-quantity-runtime-integration.md

The single batch seed commit must contain this manifest at its active path plus exact byte copies of all ten immutable task specs at the seed destinations above.

## Focused checkpoints

0061:
    .venv/bin/python -m pytest -q tests/test_migrations.py tests/test_wheel_migrations.py -k "quantity or removed or sold or discarded"
    just migration-check
    just compile
    git diff --check

0062:
    .venv/bin/python -m pytest -q tests/test_quantity_semantics.py tests/test_domain.py -k "quantity"
    just compile
    git diff --check

0063:
    .venv/bin/python -m pytest -q tests/test_quantity_split.py tests/test_domain.py -k "split or partial or move or take"
    just compile
    git diff --check

0064:
    .venv/bin/python -m pytest -q tests/test_removed_lifecycle.py tests/test_domain.py tests/test_app.py -k "removed or restore or lifecycle or duplicate or equivalent"
    just compile
    git diff --check

0065:
    .venv/bin/python -m pytest -q tests/test_agent.py tests/test_app.py tests/test_atomic_turn_receipts.py -k "quantity or partial or removed or restore or receipt"
    just provider-contract
    just compile
    git diff --check

0066:
    .venv/bin/python -m pytest -q tests/test_portable_v3.py tests/test_portable_compatibility.py tests/test_portable_streaming_import.py tests/test_storage.py -k "portable or quantity or removed"
    just compile
    git diff --check

0067:
    .venv/bin/python -m pytest -q tests/test_undo.py tests/test_atomic_turn_receipts.py tests/test_idempotency.py -k "undo or compensat or receipt"
    just compile
    git diff --check

0068:
    .venv/bin/python -m pytest -q tests/test_prompts.py tests/test_scenario_eval.py tests/test_eval_checks.py -k "quantity or partial or removed or restore or undo or russian"
    just scenario-check
    just scenario-eval
    just compile
    git diff --check

0069:
    .venv/bin/python -m pytest -q tests/test_target_scale.py tests/test_atomic_turn_receipts.py tests/test_idempotency.py tests/test_idempotency_crash.py tests/test_write_target_safety.py -k "quantity or split or removed or undo or duplicate or equivalent"
    just compile
    git diff --check

0070:
    .venv/bin/python -m pytest -q tests/test_app.py tests/test_manual_admin.py tests/test_activity.py tests/test_runtime_cli.py tests/test_database_doctor.py tests/test_storage.py tests/test_restore_rehearsal.py tests/test_migrations.py tests/test_wheel_migrations.py -k "item or quantity or removed or restore or portable or migration or backup or restore"
    just compile
    git diff --check

## Final local integration

Before the full-local gate:

    .venv/bin/python -m pytest -q \
      tests/test_quantity_semantics.py \
      tests/test_quantity_split.py \
      tests/test_removed_lifecycle.py \
      tests/test_undo.py \
      tests/test_portable_v3.py \
      tests/test_portable_compatibility.py \
      tests/test_portable_streaming_import.py \
      tests/test_agent.py \
      tests/test_app.py \
      tests/test_atomic_turn_receipts.py \
      tests/test_idempotency.py \
      tests/test_idempotency_crash.py \
      tests/test_write_target_safety.py \
      tests/test_target_scale.py \
      tests/test_migrations.py \
      tests/test_wheel_migrations.py \
      tests/test_scenario_eval.py \
      tests/test_eval_checks.py
    just provider-contract
    just compile
    git diff --check

Then run the v8 full-local sequence exactly once:

    just check
    just migration-check
    just corpus-check
    just scenario-check
    just scenario-eval
    just retrieval-eval

Do not run the full-local sequence after individual tasks.

## Scope constraints

No:
- Item merge;
- Product/SKU or stock-position entity;
- continuous measurement units or arithmetic over comments;
- automatic removal inferred only from arithmetic;
- hard delete/purge;
- general undo stack or redo;
- undo of arbitrary older actions;
- household multi-user/auth/role model;
- Telegram/WhatsApp transport implementation;
- image/media implementation;
- voice recognition;
- QR/barcodes;
- multilingual/transliteration/cross-language work;
- fuzzy/morphology/embedding search expansion;
- backup scheduling/retention/off-machine policy;
- trace purge/retention management;
- provider/model promotion;
- dependency additions unless an unavoidable blocker is demonstrated;
- Python 3.13+ verification;
- CI workflow changes.

Use existing dependencies and Python 3.12.

## Stop conditions

Stop rather than weaken the contract if implementation would require:

- storing quantity zero;
- silently inventing quantity precision or removal intent;
- merging lots to implement Undo;
- rewriting/deleting historical Events for correction;
- breaking frozen portable v1/v2 import compatibility;
- making split + requested partial operation non-atomic;
- allowing partial Undo compensation;
- bypassing stable-ID/write-target safety;
- changing product semantics from the accepted design documents.

## Final lifecycle

After 0070:
- cumulative seed..HEAD self-review;
- one pre-PR batch review;
- final integration checks;
- one full-local v8 gate;
- one PR;
- authoritative exact-head CI;
- narrow correction loop only if required;
- merge commit after green exact head;
- clean main sync;
- seed ancestry proof;
- compact post-merge completion report.
