# Assignment 0056: bounded portable import integration

## Objective

Switch the public portable import operation to the bounded reader/validator/writers delivered by 0052–0055 while preserving the hardened publication and transactional semantics from 0045–0046.

## Required behavior

- `import_portable_inventory()` must no longer call `load_portable_inventory()` or otherwise construct one complete `PortableDocument`.
- Fully validate the source into the bounded temporary workspace before creating/migrating the working application database or creating the destination parent as an import side effect.
- Preserve target preflight:
  - destination must differ from active DB;
  - destination, `-wal`, and `-shm` must be absent;
  - re-check immediately before publication.
- Replay validated inventory and events into one working-database transaction.
- Preserve current FTS reconstruction/consistency validation before commit/publication.
- Preserve 0046 race-safe no-overwrite publication and owned-file cleanup.
- Return the existing `PortableImportResult` contract with exact format/source revision and exact category/location/item/event counts from the bounded validation summary.
- Preserve source portability semantics and exclusion semantics; operational/provider/chat/evaluation tables remain absent from portable reconstruction.
- On any parser, semantic, write, FTS, physical-validation, copy, publication, fsync, or race failure:
  - no partial destination DB may be published;
  - pre-existing raced destination/sidecars remain untouched;
  - working/publish files and bounded-parser workspace are cleaned if owned by this attempt.
- Successful import must still pass `validate_database()` after staging/publication.

## Compatibility boundary

The complete-document parser may remain as a compatibility/testing API, but neither the production import path nor helpers called by it may fall back to whole-file materialization.

## Structural coverage

Inject failures at validation, mid-write, FTS validation, snapshot copy and publication stages and prove cleanup/atomicity remains at least as strong as 0045–0046.

## Constraints

No format evolution, schema migration, dependency addition, target overwrite behavior, provider/model work or product semantics.

## Focused verification

Use the manifest-declared 0056 check only.
