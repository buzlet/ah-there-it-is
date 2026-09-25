# Assignment 0057: bounded portable dry-run and compatibility

## Objective

Make the operator-facing portable preflight/dry-run path use the same bounded validation boundary as real import and prove frozen v1/current v2 compatibility.

## Required behavior

- `python -m ah_there_it_is.storage_cli import-json SOURCE DESTINATION --dry-run` must not call the whole-document `validate_portable_inventory()` path.
- Dry-run must use the bounded reader/semantic validator from 0052–0053 and return the existing JSON result fields:
  - `dry_run`;
  - source/destination;
  - format;
  - source Alembic revision;
  - exact category/location/item/event counts.
- Dry-run remains pure with respect to application databases:
  - do not create/migrate the destination;
  - do not create destination sidecars;
  - do not mutate/checkpoint the active DB.
- Target-path safety validation remains identical to real import.
- Preserve the committed hand-authored portable-v1 compatibility fixture and all v1 semantic derivation rules.
- Preserve current v2 strictness, including duplicate-key/extra-field/reference/hierarchy failures.
- Preserve direct complete-document parser helpers for callers/tests that intentionally request a complete `PortableDocument`; do not silently change their return type.
- Ensure bounded temporary parser workspace is cleaned after successful and failed dry-run.
- CLI error classification/exit behavior remains compatible.

## Coverage

Exercise:

- hand-authored v1 fixture dry-run and real import;
- current v2 export -> bounded dry-run -> bounded import;
- malformed/duplicate-key/unknown-field input;
- occupied destination and sidecar preflight;
- large event-heavy input without whole-file loading.

## Constraints

No new CLI command, format change, dependency, schema migration or product semantics.

## Focused verification

Use the manifest-declared 0057 check only.
