# Assignment 0051: bounded database physical validation

## Objective

Remove the remaining unbounded diagnostic materialization from storage-level SQLite validation without weakening backup/restore/rehearsal correctness.

Merged 0050 bounded doctor semantic/FTS samples, but `validate_database()` still performs full `fetchall()` calls for both `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.

## Required behavior

- Keep healthy-database behavior and the successful `DatabaseValidation` public shape compatible.
- Integrity validation must retain only a bounded diagnostic sample. Use SQLite's bounded integrity-check facility or an equivalent explicit bound; sample retention must never grow with the number of reported integrity errors.
- Foreign-key validation must:
  - preserve exact pass/fail correctness;
  - obtain an exact violation count without retaining all violation rows where SQLite supports a count/projection query;
  - retain at most 20 deterministic sample rows for an error report.
- Error text must state the exact FK count and bounded samples, not stringify an unbounded tuple.
- Do not use `fetchall()` on an unbounded integrity/FK violation result.
- Preserve read-only behavior. Validation must not checkpoint, repair, create sidecars for, or otherwise mutate the candidate database.
- Backup validation, restore validation, rollback validation and restore rehearsal must inherit the bounded behavior automatically.
- Wrong Alembic revision behavior remains unchanged.

## Structural coverage

Add deterministic corruption fixtures with thousands of FK violations and prove:

- failure remains exact;
- retained samples are <=20 and deterministic;
- validation does not iterate/store the complete FK result merely to truncate it;
- healthy and wrong-revision databases retain their existing behavior;
- WAL/read-only source state is not mutated.

Do not use timing thresholds.

## Constraints

No schema/migration change, repair behavior, backup/restore semantic redesign, dependency addition, CLI contract redesign, or product semantics.

## Focused verification

Use the manifest-declared 0051 check only.
