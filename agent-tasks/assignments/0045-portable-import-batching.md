# Assignment 0045: portable import write batching

## Objective

Remove avoidable per-row flush/write amplification from portable import while preserving exact IDs, referential integrity and portable-v1/v2 compatibility.

Current `_write_portable_inventory()` flushes repeatedly inside category/location/tag loops.

## Requirements

- Preserve explicit category/location/item/event IDs from the document.
- Preserve tree parent dependencies and deterministic behavior.
- Batch categories/locations/items/aliases/item-tags/events where dependency ordering allows.
- Resolve tags without one flush per tag name.
- Keep all writes inside the existing single transaction.
- Preserve rollback-on-error behavior.
- Preserve FTS/search validation after import.
- Do not bypass semantic validation.

## Structural tests

At target scale:
- measure SQL statement count using SQLAlchemy events;
- prove statement count is not linear due solely to per-row flushes;
- prove no N+1 tag resolution;
- prove v1 and v2 fixtures still import identically;
- prove Session rollback leaves no destination publication on a mid-import error.

No wall-clock thresholds.

## Constraints

No bulk method that bypasses required SQLAlchemy/default/relationship semantics unless tests prove all invariants. No schema/index changes.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_import"
just compile
git diff --check
```
Then commit checkpoint 0045.
