# Assignment 0054: streaming portable tree/item import

## Objective

Write validated portable categories, locations and items from the bounded workspace into the migrated working database without reconstructing the full inventory object graph.

## Required behavior

- Consume the validated/spooled source produced by 0052–0053.
- Preserve explicit stable IDs and all current persisted inventory semantics.
- Categories and Locations must respect parent-before-child dependencies while accepting arbitrary source-array order.
- Tree working state may retain compact node ID/parent/depth information; it must not retain full serialized node payloads after use.
- Insert Items in deterministic bounded batches without hydrating all Items into the ORM identity map.
- Preserve:
  - names/descriptions/state;
  - category/current-location references;
  - v2 `location_status`;
  - v1 conservative location-status derivation;
  - quantity/attributes;
  - created/updated timestamps.
- Aliases and item/tag links must be written in bounded batches.
- Tag identity/spelling semantics must remain identical to current portable import. Internal Tag IDs are implementation detail but must be deterministic for the same validated source.
- Do not add per-row flush/query loops. Query/write counts must remain bounded by batch/section structure rather than item cardinality.
- This task may expose internal writer helpers; the public `import_portable_inventory()` switch happens in 0056.

## Structural coverage

At >=1000 items with aliases/tags:

- prove bounded batch sizes;
- prove no Item ORM identity-map growth to the whole inventory;
- prove no N+1 write/query pattern;
- verify exact reconstructed inventory rows before events are considered.

## Constraints

No Event import yet, no publication-path change, no schema/migration change, no format change, no dependency addition.

## Focused verification

Use the manifest-declared 0054 check only.
