# Assignment 0048: backup overwrite failure atomicity

## Objective

Harden explicit `overwrite=True` backup replacement against failures around publication and durability steps.

## Required guarantees

Before publication:
- existing destination remains untouched if snapshot copy or candidate validation fails.

At publication:
- replacement is same-filesystem atomic.

After publication:
- failures from file/directory fsync are surfaced explicitly;
- no temporary artifacts remain;
- resulting destination is either the previous valid backup or the newly validated backup, never a partial file.

Do not promise rollback after a successful atomic replace if the platform reports a later durability failure and the old inode is no longer available. Instead make this failure state explicit and validate the destination when feasible.

## Tests

Fault-inject:
- snapshot copy failure;
- validation failure;
- replace failure;
- file fsync failure;
- directory fsync failure.

For each, assert the strongest correct invariant above and no temp leakage.

Also preserve uncheckpointed WAL backup coverage.

## Constraints

No versioned backup retention policy or automated backup scheduling.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "backup"
just compile
git diff --check
```
Then commit checkpoint 0048.
