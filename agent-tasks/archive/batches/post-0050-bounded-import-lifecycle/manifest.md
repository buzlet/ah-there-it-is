# Batch manifest: bounded portable import and lifecycle alignment 0051–0060

Batch ID: `post-0050-bounded-import-lifecycle-2026-09-25`

Protocol: `agent-tasks/common/v8.md`

Expected start main:

`c6609139e16384e3de48f9b403a426dcf2fa9e9c`

Implementation branch:

`feat/bounded-import-lifecycle-0051-0060`

Execution user:

`rdu01`

Required work directory:

`/home/rdu01/projects/bounded-import-lifecycle-0051-0060`

Batch review destination:

`agent-tasks/reviews/0051-0060-bounded-import-lifecycle-r1.md`

Full local regression:

`full_local_required: true`

## Execution

Direct U24 shell, already running as `rdu01`.

All Git/edit/Python/Just/test operations must occur only inside:

`/home/rdu01/projects/bounded-import-lifecycle-0051-0060`

No `sudo`, no `su`, no other checkout.

If absent, create a fresh canonical checkout at that exact path.

For independent shell calls use only:

`cd /home/rdu01/projects/bounded-import-lifecycle-0051-0060 || exit 1`

Do not export or activate the venv in shell.

Direct Python commands use `.venv/bin/python`.
Just recipes use plain `just`; the repository Justfile owns the absolute repo-local venv PATH.

## Objective

Close the remaining bounded-memory recovery gap after 0041–0050 and align the lifecycle helper with the actual integrated-batch v8 process.

The batch has two coherent parts:

1. storage/import hardening: bounded physical validation and a genuinely bounded portable import/dry-run path that does not materialize one complete JSON/Pydantic document;
2. process hardening: make `lifecycle_checkpoints.py` understand and verify the current one-branch integrated-batch v8 manifest/seed/checkpoint model.

No product/domain semantic expansion is allowed.

## Ordered tasks

1. 0051 — bounded database physical validation
2. 0052 — streaming portable input reader
3. 0053 — bounded portable semantic validation
4. 0054 — streaming portable tree/item import
5. 0055 — streaming portable event import
6. 0056 — bounded portable import integration
7. 0057 — bounded portable dry-run and compatibility
8. 0058 — portable import scale/failure regression
9. 0059 — integrated-batch manifest/preflight support
10. 0060 — integrated-batch seed/checkpoint lifecycle

Exact task specs:
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0051-bounded-database-validation.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0052-streaming-portable-input-reader.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0053-bounded-portable-semantic-validation.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0054-streaming-portable-tree-item-import.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0055-streaming-portable-event-import.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0056-bounded-portable-import-integration.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0057-bounded-portable-dry-run-compatibility.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0058-portable-import-scale-regression.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0059-integrated-batch-manifest-preflight.md`
- `agent-tasks/batches/post-0050-bounded-import-lifecycle/0060-integrated-batch-seed-checkpoints.md`

Seed destinations:
- `agent-tasks/assignments/0051-bounded-database-validation.md`
- `agent-tasks/assignments/0052-streaming-portable-input-reader.md`
- `agent-tasks/assignments/0053-bounded-portable-semantic-validation.md`
- `agent-tasks/assignments/0054-streaming-portable-tree-item-import.md`
- `agent-tasks/assignments/0055-streaming-portable-event-import.md`
- `agent-tasks/assignments/0056-bounded-portable-import-integration.md`
- `agent-tasks/assignments/0057-bounded-portable-dry-run-compatibility.md`
- `agent-tasks/assignments/0058-portable-import-scale-regression.md`
- `agent-tasks/assignments/0059-integrated-batch-manifest-preflight.md`
- `agent-tasks/assignments/0060-integrated-batch-seed-checkpoints.md`

The single batch seed commit must contain this manifest at its active path plus exact byte copies of all ten immutable task specs at the seed destinations above.

## Focused checkpoints

0051:
```text
.venv/bin/python -m pytest -q tests/test_storage.py tests/test_restore_rehearsal.py -k "validate or integrity or foreign or backup or restore"
just compile
git diff --check
```

0052:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py -k "reader or json or spool"
just compile
git diff --check
```

0053:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py -k "validation or semantic or reference or duplicate or hierarchy"
just compile
git diff --check
```

0054:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py -k "tree or item or alias or tag or inventory_write"
just compile
git diff --check
```

0055:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py -k "event or history"
just compile
git diff --check
```

0056:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py tests/test_storage.py -k "portable_import"
just compile
git diff --check
```

0057:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py tests/test_portable_compatibility.py tests/test_runtime_cli.py -k "portable or import_json or dry_run"
just compile
git diff --check
```

0058:
```text
.venv/bin/python -m pytest -q tests/test_portable_streaming_import.py tests/test_storage.py tests/test_target_scale.py tests/test_portable_compatibility.py -k "portable"
just compile
git diff --check
```

0059:
```text
.venv/bin/python -m pytest -q tests/test_lifecycle_checkpoints.py -k "manifest or preflight"
just compile
git diff --check
```

0060:
```text
.venv/bin/python -m pytest -q tests/test_lifecycle_checkpoints.py
just compile
git diff --check
```

## Final local integration

Before the full-local gate run:

```text
.venv/bin/python -m pytest -q \
  tests/test_storage.py \
  tests/test_restore_rehearsal.py \
  tests/test_portable_streaming_import.py \
  tests/test_portable_compatibility.py \
  tests/test_runtime_cli.py \
  tests/test_target_scale.py \
  tests/test_lifecycle_checkpoints.py
just compile
git diff --check
```

Then, because this batch changes storage/import and verification tooling, run the v8 full-local sequence exactly once:

```text
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
```

Do not run the full-local sequence after individual tasks.

## Scope constraints

No:
- schema/index migration;
- portable-v3 or portable-v2 field/semantic change;
- quantity/physical-instance, split/merge, partial quantity operations;
- correction/undo/hard-delete policy;
- trace-retention policy;
- automated backup scheduling/retention/off-machine policy;
- remote/multi-user/auth work;
- provider/model behavior;
- dependency additions;
- Python 3.13+ verification work;
- CI workflow changes;
- search/ranking changes.

Use the Python standard library and existing project dependencies only.

If the bounded import design would require weakening strict validation, frozen v1 compatibility, target publication safety, or transactional atomicity, stop and report a blocker instead.

## Failure discipline

After any failed file-changing command, inspect:
- `git status --short`;
- `git diff`;
- `git diff --cached`;
- current target contents.

Then construct a new edit from current state. Do not blindly replay the same failed patch transport.

## Final lifecycle

After 0060:
- cumulative seed..HEAD self-review;
- one batch review containing only pre-PR facts per v8;
- final integration set;
- one full-local v8 regression;
- one PR;
- authoritative exact-head CI;
- narrow correction loop if required;
- merge commit only after green exact head;
- clean main sync;
- seed ancestry proof;
- post-merge completion report with exact PR/head/CI/merge/final-main facts.

Return one compact batch report.
