# Batch review: storage/recovery hardening 0041–0050 (R1)

## Review scope

- Seed: `f9a76bfc356c4fb414e74c068e508b137cbe4647`
- Reviewed head: `6253ea21473f8766558e9d0d333b216fe62145ba`
- Tasks: `0041` through `0050`, in manifest order
- Production files: `storage.py`, `storage_cli.py`, `database_doctor.py`
- Test files: `test_storage.py`, `test_database_doctor.py`

## Outcome

No unresolved correctness, data-loss, concurrency, or scope findings.

The cumulative change preserves portable-v2 semantics while replacing ORM graph export with scalar projections and a bounded streaming publication path. Export reads use one explicit SQLite snapshot. Import writes are batched, final publication is no-overwrite and race-aware, and failed imports retain no partially published database owned by the operation.

Backup publication now has atomic no-overwrite behavior. Overwrite failures distinguish pre-publication failure from a published destination whose durability sync failed. Restore validates the candidate and safety copy before publication, and post-publication failures attempt a validated rollback while preserving both failure contexts if rollback also fails.

Database doctor now obtains exact violation counts with bounded, deterministic samples. Identity and scalar diagnostics use SQL count/sample projections; PRAGMA results stream through bounded accumulation; cycle analysis retains only required hierarchy state plus bounded samples; existing FTS repair authorization is unchanged.

## Scope and compatibility review

- No migrations, dependency changes, CI workflow changes, provider/model changes, or domain-semantic expansion.
- Portable format and excluded-data policy are unchanged.
- Existing CLI output fields remain available; export CLI now reports counts from the streaming result.
- Repair remains limited to derived FTS objects.
- Temporary and publication files are cleaned on covered failure paths; intentionally published destinations and safety backups are retained when their state must be reported to the operator.

## Verification reviewed

Each task passed its manifest-declared focused pytest selection, `just compile`, and `git diff --check` before its checkpoint commit. Scale, WAL snapshot, publication race, injected copy/validation/replace/fsync, rollback, and bounded-diagnostic cases are represented in focused tests.

Final integration and the single full-local v8 gate remain to be recorded after this review.
