# Assignment 0044: portable export snapshot consistency

## Objective

Guarantee that one portable export represents one coherent SQLite read snapshot even when another connection commits during export.

The export performs multiple projection queries. It must never mix pre-commit and post-commit inventory/history rows in one document.

## Requirements

- Establish an explicit coherent read transaction/snapshot for the complete portable export.
- Support active WAL mode without checkpointing or mutating the source database.
- Concurrent committed changes may appear entirely before or entirely after an export snapshot, but never partially across its arrays.
- Export must not block longer than SQLite's normal read-snapshot requirements.
- No writes/checkpoints to the active database from export.

## Tests

Use two independent SQLite connections and synchronization/fault hooks, not timing sleeps.

Prove:
- writer commits between two export projection phases;
- produced document corresponds wholly to one logical state;
- source main/WAL bytes are not changed by export except changes made by the intentional writer;
- export succeeds with committed uncheckpointed WAL data;
- repeated export after the writer commit sees the new complete state.

## Constraints

No schema/index changes and no backup/restore behavior changes.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_export and snapshot"
just compile
git diff --check
```
Then commit checkpoint 0044.
