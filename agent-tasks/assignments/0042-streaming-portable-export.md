# Assignment 0042: streaming portable JSON publication

## Objective

Make the normal portable export file path memory-bounded and incrementally serialized.

0041 provides scalar/projection readers. 0042 must stop building the complete portable document in memory before writing the destination file.

## Contract

Keep the CLI command and portable-v2 JSON contract:

```bash
python -m ah_there_it_is.storage_cli export-json DESTINATION
```

Output file remains one valid portable-v2 JSON object with:
- `format`;
- `exported_at`;
- `source`;
- `inventory.categories`;
- `inventory.locations`;
- `inventory.items`;
- `history.events`;
- `excluded`.

Preserve deterministic array ordering and non-ASCII text.

## Writer

- Write to a same-directory temporary file and publish only after complete successful serialization.
- Serialize large arrays incrementally; do not construct one full Python document containing all rows.
- Writer must be lazy enough to prove first output bytes are written before all source rows are consumed.
- Failure during iteration/serialization must leave any existing destination unchanged and remove temporary artifacts.
- Successful publication must retain existing fsync durability behavior.
- Expose a compact typed export result/summary sufficient for CLI counts without requiring a full returned document.

If a compatibility helper returning a full document is still needed only by tests/internal callers, keep it clearly separate from the normal CLI streaming path; the CLI must use the streaming path.

## Tests

Cover zero/one/many arrays, Unicode, parseable JSON, laziness, failure cleanup, existing-destination preservation, and target-scale output completeness.

## Constraints

No portable schema/version change, no import change, no dependency, no migration.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable_export"
just compile
git diff --check
```
Then commit checkpoint 0042.
