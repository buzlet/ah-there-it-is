# Assignment 0041: portable export scalar projection

## Objective

Remove ORM-graph materialization from the portable inventory export read path while preserving the frozen portable-v2 document semantics.

Current `_portable_document()` materializes complete `Category`, `Location`, `Item`, alias/tag relationships and `Event` ORM objects before serialization.

Introduce dedicated typed scalar/projection readers for portable export.

## Requirements

- Preserve portable-v2 field names, values and deterministic ID ordering.
- Read categories, locations, items, aliases/tags and events using scalar/projection SQL rather than full ORM entity graphs.
- Avoid populating the Session identity map proportionally to export history size.
- Avoid N+1 reads for aliases/tags.
- Keep alias order by alias ID and tag order by tag ID, matching current output.
- Keep provider/agent/experiment data excluded.
- Keep validation/source revision behavior unchanged.
- No arbitrary row limit.

A small set of immutable dataclasses/typed projections is preferred.

## Tests

Add focused structural coverage proving:
- existing fixture export parses identically;
- item aliases/tags retain deterministic order;
- 1000-item export read does not materialize 1000 Item ORM objects in the identity map;
- query count is bounded by projection groups, not per item;
- no LIMIT cap truncates export rows.

Do not require streaming file output yet; that is 0042.

## Constraints

No schema migration, portable format change, dependency addition, import behavior change, backup/restore change, or product semantics change.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_export"
just compile
git diff --check
```
Then commit checkpoint 0041.
