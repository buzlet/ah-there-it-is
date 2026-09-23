# Assignment 0018: restore rehearsal and semantic validation

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/hardening-restore-rehearsal`

## Objective

Provide a safe way to prove that a backup can be restored and is semantically healthy without touching the configured active database.

This is a maintenance assignment and does not consume/redefine product Stage 26.

## Required behavior

- Add an explicit storage-level restore rehearsal operation for a supplied SQLite backup candidate.
- The rehearsal must never replace, mutate, checkpoint or create sidecars for the configured active database.
- Exercise the real restore machinery against an isolated temporary fake-active database:
  1. create an isolated temporary workspace;
  2. seed a fake active database from a safe snapshot of the configured active database or equivalent valid current database;
  3. invoke the same restore path used by real restore against that fake active target and the supplied candidate;
  4. run physical validation on the restored fake target;
  5. run the current application doctor against the restored fake target;
  6. clean all temporary database/sidecar/safety files.
- Return machine-readable results that distinguish:
  - restore mechanics success/failure;
  - SQLite integrity/FK/schema validation;
  - application/domain/FTS doctor health.
- Add `python -m ah_there_it_is.storage_cli restore-rehearsal <candidate>` (or an equivalently clear explicit storage CLI command). Exit success only when restore mechanics, physical validation and doctor health all pass; semantic-unhealthy candidates must produce a non-success result without touching active data.
- WAL-safe backup candidates must be supported through the existing snapshot/restore mechanisms rather than raw file-copy assumptions.
- Prove the configured active database bytes/state are unchanged across both successful and failed rehearsal attempts.
- Cover:
  - healthy candidate;
  - SQLite-invalid candidate;
  - wrong Alembic revision;
  - SQLite-valid but doctor-unhealthy/domain/FTS-corrupt candidate;
  - cleanup after failure;
  - installed-wheel CLI behavior.

## Constraints

Do not add automatic backup scheduling/reminders, service-manager integration, online active-database swap coordination, cloud storage, retention policy, schema changes, provider work, dependency/runtime/workflow upgrades or unrelated refactoring.

## Focused verification

Run focused storage/doctor/CLI/WAL/installed-wheel tests, then the canonical v4 verification set.
