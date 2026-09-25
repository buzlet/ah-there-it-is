# Assignment 0055: streaming portable event import

## Objective

Import portable history from the bounded workspace without retaining the complete Event history in Python.

## Required behavior

- Consume validated event records one at a time or in explicit bounded batches.
- Preserve every portable Event field exactly:
  - stable ID;
  - event_type;
  - item_id;
  - from/to Location IDs;
  - payload;
  - original_text;
  - created_at.
- Accept arbitrary source event-array order; do not require exporter order.
- Do not create a Python list of all Event objects or load the full Event history into the ORM identity map.
- Use bounded Core/ORM batches appropriate to the existing FTS/foreign-key behavior.
- All events must participate in the same eventual portable-import transaction as inventory rows.
- A late event write/validation failure must be rollback-safe and leave no committed working-domain subset.
- Event payload size may be large; only the current batch may be retained.

## Structural coverage

Use thousands of Events, including large payload/text values, and prove:

- bounded retained batches;
- exact stable IDs and fields;
- event references remain correct;
- rollback removes earlier staged inventory/events after an injected late failure.

## Constraints

No history semantic changes, event compaction/retention policy, schema changes, publication change or dependency addition.

## Focused verification

Use the manifest-declared 0055 check only.
