# Assignment 0047: race-safe backup no-overwrite contract

## Objective

Make `create_backup(..., overwrite=False)` truly no-overwrite under a destination race.

Current flow checks `target.exists()` and later calls `os.replace()`; a file created between those operations can be overwritten.

## Requirements

For `overwrite=False`:
- publish using no-overwrite semantics;
- a destination appearing at any point before publication must survive unchanged;
- raise `StorageError`;
- clean temporary backup artifacts;
- preserve existing active DB/WAL state;
- successful backup retains validation/fsync behavior.

For `overwrite=True`, preserve current explicit replacement semantics; do not change that contract in this task.

## Tests

Deterministically inject a destination creation after validation but before publication.

Assert:
- raced destination bytes unchanged;
- backup operation fails clearly;
- no temporary file remains;
- active database validates and remains unchanged;
- normal no-overwrite success still works.

## Constraints

No CLI flag changes, no backup naming policy change.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "backup and (overwrite or race)"
just compile
git diff --check
```
Then commit checkpoint 0047.
