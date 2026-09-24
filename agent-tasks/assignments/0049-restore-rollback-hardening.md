# Assignment 0049: restore rollback hardening

## Objective

Strengthen failure handling after the active DB replacement point in `restore_backup()`.

Current code attempts rollback from the safety backup if post-replace validation fails. Make rollback outcome explicit and verifiable.

## Requirements

- Safety backup must be created and validated before destructive restore publication.
- If candidate staging/validation fails before publication, active DB is untouched.
- If restored target fails validation after publication, restore the safety backup.
- After rollback publication, validate the active target again.
- If rollback succeeds, re-raise/report the original restore failure with clear indication that rollback succeeded.
- If rollback itself fails or the rolled-back target does not validate, raise a dedicated/clear `StorageError` containing both restore and rollback failure context; never silently claim recovery.
- Never delete the safety backup on failure.
- Clean replacement/rollback temporary files and stale target sidecars as appropriate.
- Preserve WAL-safe checkpoint/sidecar semantics.

## Fault-injection tests

Exercise failures at:
- candidate copy;
- candidate staging validation;
- active checkpoint;
- replace;
- post-replace validation;
- rollback copy;
- rollback replace;
- rollback validation.

Use deterministic monkeypatch/fault injection, not timing.

Verify active/safety database validity and bytes/content appropriate to each stage.

## Constraints

No automated backup retention policy, no remote storage, no schema changes.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py tests/test_restore_rehearsal.py -k "restore"
just compile
git diff --check
```
Then commit checkpoint 0049.
