# Assignment 0046: portable import publication race safety

## Objective

Close destination/sidecar TOCTOU gaps around publishing a newly imported SQLite database.

Current code rechecks the destination before `_publish_new_file()`, but publication must remain safe if the destination or SQLite sidecars appear in the race window.

## Requirements

When import was requested for a genuinely new destination:
- never overwrite a destination file that appears concurrently;
- never publish beside pre-existing/concurrently appearing `-wal` or `-shm` sidecars;
- report a clear `StorageError`;
- remove temporary working/publish files;
- leave the concurrently created destination/sidecars byte-for-byte untouched;
- never leave a partially published application DB.

Use an atomic/no-overwrite publication primitive where possible; make sidecar checks safe enough for the supported local POSIX filesystem model and document unavoidable filesystem assumptions in code comments.

## Tests

Inject deterministic races immediately before publication:
- main destination appears;
- WAL appears;
- SHM appears;
- publication primitive fails.

Assert no overwrite, cleanup, and source/active DB untouched.

## Constraints

No lock daemon, dependency, schema change or global filesystem architecture change.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_import and (race or publish or destination)"
just compile
git diff --check
```
Then commit checkpoint 0046.
