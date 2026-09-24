# Batch review: storage/recovery hardening 0041–0050 (R1)

## Provenance

- Batch: `post-0040-storage-recovery-hardening-2026-09-25`
- Control SHA: `77a9e6cb35c9c9efbfa3335e3d9a61d953fdba24`
- Expected and observed start main: `6e59e0285cf308d8329841ebf40d7162f49bcbec`
- Seed: `f9a76bfc356c4fb414e74c068e508b137cbe4647`
- Reviewed implementation head: `5717db74b2e90a9f54cfbfc923416c36e988bed4`
- Implementation branch: `feat/storage-recovery-hardening-0041-0050`

## Task checkpoints

### 0041 — portable export projection

- Range: `f9a76bf..755e387`
- Focused: `tests/test_storage.py -k "portable_export"` — 2 passed
- Compile/diff-check: green
- Corrections: 1; aligned the structural query assertion with the stricter six-query implementation.

### 0042 — streaming portable export

- Range: `755e387..91f0a3b`
- Focused: `tests/test_storage.py -k "portable_export"` — 4 passed
- Compile/diff-check: green
- Corrections: 0

### 0043 — portable roundtrip scale

- Range: `91f0a3b..0fbbaa4`
- Focused: `tests/test_storage.py -k "portable and roundtrip"` — 1 passed
- Compile/diff-check: green
- Corrections: 0

### 0044 — portable export snapshot consistency

- Range: `0fbbaa4..0efcbd4`
- Focused: `tests/test_storage.py -k "portable_export and snapshot"` — 1 passed
- Compile/diff-check: green
- Corrections: 1; made the controlled concurrent insert compatible with the location-truth trigger.

### 0045 — portable import batching

- Range: `0efcbd4..1edb3f0`
- Focused: `tests/test_storage.py -k "portable_import"` — 4 passed
- Compile/diff-check: green
- Corrections: 1; replaced per-row alias/tag writes with Core executemany and deterministic tag IDs.

### 0046 — portable import publication race

- Range: `1edb3f0..a3d1f2c`
- Focused: `tests/test_storage.py -k "portable_import and (race or publish or destination)"` — 4 passed
- Compile/diff-check: green
- Corrections: 2; covered primitive publication failure, then replaced a platform-dependent WAL file hash assertion with semantic inventory and excluded-record checks.

### 0047 — backup no-overwrite race

- Range: `a3d1f2c..ca0f43e`
- Focused: `tests/test_storage.py -k "backup and (overwrite or race)"` — 2 passed
- Compile/diff-check: green
- Corrections: 0

### 0048 — backup overwrite failure atomicity

- Range: `ca0f43e..df5eadc`
- Focused: `tests/test_storage.py -k "backup"` — 9 passed
- Compile/diff-check: green
- Corrections: 0

### 0049 — restore rollback hardening

- Range: `df5eadc..d50be1e`
- Focused: storage and rehearsal restore selection — 16 passed
- Compile/diff-check: green
- Corrections: 1; wrapped staging copy/validation failures with stage-specific `StorageError` context.

### 0050 — doctor bounded diagnostics

- Range: `d50be1e..6253ea2`
- Focused: `tests/test_database_doctor.py` — 18 passed
- Compile/diff-check: green
- Corrections: 1; generated controlled invalid location rows without leaving validation triggers altered.

## Cumulative review

No unresolved correctness, data-loss, concurrency, or scope findings in `seed..HEAD`.

- Portable-v2 semantics and exclusions remain unchanged; export uses scalar projections, bounded batches, same-directory atomic publication, and one explicit SQLite snapshot.
- Import uses bounded write batching and race-safe no-overwrite publication with owned-file cleanup.
- Backup distinguishes pre-publication failures from published durability failures; no-overwrite publication is atomic.
- Restore validates safety/candidate stages and reports both restore and rollback outcomes without hiding the original failure.
- Doctor preserves exact counts with deterministic samples bounded to 20; repair remains limited to derived FTS state.
- No migrations, dependencies, CI workflow changes, provider/model changes, or domain-semantic expansion.

## Final local verification

- Final integration after correction: four manifest modules green; compile and diff-check green.
- `just check`: 450 passed, one third-party deprecation warning.
- `just migration-check`: green; no new upgrade operations.
- `just corpus-check`: 58 cases.
- `just scenario-check`: 58 scenarios.
- `just scenario-eval`: 58/58 completed with checks passing.
- `just retrieval-eval`: 86/86 passed.

## Deviations and corrections

The first full-local attempt exposed that the start-main `Justfile` exported relative `.venv/bin`. Tests changing subprocess working directory inherited `sys.executable == '.venv/bin/python'` and could not launch it. The correction uses `justfile_directory() + "/.venv/bin"`; this is evaluated per checkout, so every local or CI host receives its own absolute workspace path. It does not hardcode `/home/rdu01/...` and does not alter CI configuration.

The second attempt exposed a physical SHA assertion on an active WAL database. SQLite may change physical pages or headers during read/checkpoint activity without changing logical content. The corrected race test proves semantic portable equality, operational-only record counts, search identity, source/concurrent-path preservation, and staging cleanup.

After both narrow corrections, affected focused checks, final integration, and the complete full-local sequence were green.

## PR, CI, and merge

- PR: pending
- Exact-head authoritative CI: pending
- Merge commit: pending
- Final main sync and seed ancestry: pending
