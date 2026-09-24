# Batch manifest: storage/recovery hardening 0041–0050

Batch ID: `post-0040-storage-recovery-hardening-2026-09-25`

Protocol: `agent-tasks/common/v8.md`

Expected start main:

`6e59e0285cf308d8329841ebf40d7162f49bcbec`

Implementation branch:

`feat/storage-recovery-hardening-0041-0050`

Execution user:

`rdu01`

Required work directory:

`/home/rdu01/projects/storage-recovery-hardening-0041-0050`

Batch review destination:

`agent-tasks/reviews/0041-0050-storage-recovery-hardening-r1.md`

Full local regression:

`full_local_required: true`

## Execution

Direct U24 shell, already running as `rdu01`.

All Git/edit/Python/Just/test operations must occur only inside:

`/home/rdu01/projects/storage-recovery-hardening-0041-0050`

No `sudo`, no `su`, no other checkout.

If absent, create a fresh canonical checkout at that exact path.

For independent shell calls use the existing execution convention:
```bash
cd /home/rdu01/projects/storage-recovery-hardening-0041-0050 || exit 1
```

Do not export or activate the venv in shell.
Direct Python commands use `.venv/bin/python`.
Just recipes use plain `just`; Justfile owns repo-local venv preference.

## Objective

Harden portable export/import, backup/restore and database-doctor behavior for scale, concurrency and injected failures without changing product/domain semantics.

## Ordered tasks

1. 0041 — portable export projection
2. 0042 — streaming portable export
3. 0043 — portable roundtrip scale
4. 0044 — portable export snapshot consistency
5. 0045 — portable import batching
6. 0046 — portable import publication race
7. 0047 — backup no overwrite race
8. 0048 — backup overwrite failure atomicity
9. 0049 — restore rollback hardening
10. 0050 — doctor bounded diagnostics

Exact task specs:
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0041-portable-export-projection.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0042-streaming-portable-export.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0043-portable-roundtrip-scale.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0044-portable-export-snapshot-consistency.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0045-portable-import-batching.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0046-portable-import-publication-race.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0047-backup-no-overwrite-race.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0048-backup-overwrite-failure-atomicity.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0049-restore-rollback-hardening.md`
- `agent-tasks/batches/post-0040-storage-recovery-hardening/0050-doctor-bounded-diagnostics.md`

Seed destinations:
- `agent-tasks/assignments/0041-portable-export-projection.md`
- `agent-tasks/assignments/0042-streaming-portable-export.md`
- `agent-tasks/assignments/0043-portable-roundtrip-scale.md`
- `agent-tasks/assignments/0044-portable-export-snapshot-consistency.md`
- `agent-tasks/assignments/0045-portable-import-batching.md`
- `agent-tasks/assignments/0046-portable-import-publication-race.md`
- `agent-tasks/assignments/0047-backup-no-overwrite-race.md`
- `agent-tasks/assignments/0048-backup-overwrite-failure-atomicity.md`
- `agent-tasks/assignments/0049-restore-rollback-hardening.md`
- `agent-tasks/assignments/0050-doctor-bounded-diagnostics.md`

The single seed commit contains exact copies of this manifest and all ten task specs in their active destinations.

## Focused checkpoints

0041:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_export"
just compile
git diff --check
```

0042:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_export"
just compile
git diff --check
```

0043:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable and roundtrip"
just compile
git diff --check
```

0044:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_export and snapshot"
just compile
git diff --check
```

0045:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_import"
just compile
git diff --check
```

0046:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_import and (race or publish or destination)"
just compile
git diff --check
```

0047:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "backup and (overwrite or race)"
just compile
git diff --check
```

0048:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "backup"
just compile
git diff --check
```

0049:
```text
.venv/bin/python -m pytest -q tests/test_storage.py tests/test_restore_rehearsal.py -k "restore"
just compile
git diff --check
```

0050:
```text
.venv/bin/python -m pytest -q tests/test_database_doctor.py
just compile
git diff --check
```

## Final local integration

Before the full-local gate run:

```text
.venv/bin/python -m pytest -q   tests/test_storage.py   tests/test_restore_rehearsal.py   tests/test_database_doctor.py   tests/test_runtime_cli.py
just compile
git diff --check
```

Then, because `full_local_required: true`, run the v8 full-local sequence exactly once:

```text
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
```

Do not run this full-local sequence after individual tasks.

## Scope constraints

No:
- schema/index migration;
- portable-v2 field/semantic change;
- quantity/physical-instance semantics;
- correction/undo/hard-delete policy;
- trace-retention policy;
- automated backup scheduling/retention/off-machine design;
- remote/multi-user/auth work;
- provider/model behavior;
- new dependencies;
- CI workflow changes.

If a task requires any of these, stop and report a design blocker.

## Failure discipline

After any failed file-changing command, inspect:
- `git status --short`;
- `git diff`;
- `git diff --cached`;
- current target contents.

Then construct a new edit from current state. Do not blindly replay the same patch transport.

## Final lifecycle

After 0050:
- cumulative seed..HEAD self-review;
- one batch review;
- final integration set;
- one full-local v8 regression;
- one PR;
- authoritative exact-head CI;
- narrow correction loop if required;
- merge commit only after green exact head;
- sync clean main;
- prove seed ancestry and local main == origin/main.

Return one compact batch report.
