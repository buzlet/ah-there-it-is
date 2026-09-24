# Assignment 0005: Stage 16 safe bootstrap inventory import

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage16-bootstrap-import`

## Objective

Add a deterministic, provider-independent bootstrap import for initially populating an empty inventory from a human/agent-authored manifest. This is an onboarding path, not disaster recovery: it must remain separate from the frozen `inventory-portable-v1` archive format and must use normal current-domain services so generated IDs, normalized state, FTS, and item-created history are owned by the current application.

## Bootstrap format

Introduce a strict versioned JSON format named `inventory-bootstrap-v1` with this conceptual shape:

```json
{
  "format": "inventory-bootstrap-v1",
  "locations": [{"path": ["Office", "Desk", "Right drawer"], "description": null}],
  "categories": [{"path": ["Electronics", "Adapters"], "description": null}],
  "items": [{
    "name": "USB-SATA adapter",
    "description": null,
    "state": "working",
    "category_path": ["Electronics", "Adapters"],
    "location_path": ["Office", "Desk", "Right drawer"],
    "quantity": 1,
    "attributes": {},
    "aliases": [],
    "tags": []
  }]
}
```

- Paths are arrays of non-blank name components, never slash-delimited strings.
- The manifest contains no database IDs, normalized fields, timestamps, FTS state, events/history, conversations, request/evaluation/provider state, or migration revision.
- `description`, `category_path`, and `location_path` may be null where the domain allows it.
- No v2 format or compatibility conversion is part of this assignment.

## Required implementation

1. Add a separate bootstrap module/service boundary; do not fold onboarding semantics into portable recovery parsing/import.
   - Use strict typed validation with unknown-field rejection and an explicit format-version dispatch boundary.
   - Parsing/semantic validation must be pure: no database creation or writes.
   - Reject unsupported format identifiers clearly.

2. Validate hierarchy and item semantics completely before mutation.
   - Every path component must be non-blank.
   - Reject duplicate location/category paths after component-wise current identity normalization.
   - Every non-root location/category path must have its immediate parent path explicitly present in the same manifest.
   - Item `location_path` and `category_path` references must resolve to manifest paths when non-null.
   - Reject duplicate item identities using the current item identity rule: normalized item name within normalized category identity.
   - Validate current `ItemState`, quantity >= 1, attributes object shape, aliases/tags non-blank, and duplicate normalized aliases/tags within an item.
   - Do not accept serialized normalized/search-derived fields.

3. Import only into an already-created, current-schema database whose inventory domain is empty.
   - Do not create or migrate the active database automatically. The operator must use the existing explicit migration command first.
   - Before mutation, require all inventory-domain tables to contain no domain data: categories, locations, items, aliases, tags, item_tags, and events.
   - If any inventory-domain data exists, fail with a clear error. There is no merge, upsert, overwrite, replace, or partial-import mode in Stage 16.
   - Operational tables outside the inventory domain must not be read as bootstrap input or modified by bootstrap import.

4. Apply the validated manifest through normal domain/service behavior in one transaction.
   - Create categories and locations parent-before-child through `InventoryService(autocommit=False)` or an equivalent current service-owned path.
   - Resolve item category/location references from entities created in that same transaction.
   - Create every item through normal `InventoryService.create_item` behavior so normalized names, aliases/tags, FTS triggers, generated IDs, timestamps, and `item_created` events are current-domain output rather than imported state.
   - Give bootstrap-created item history an explicit stable provenance marker in `original_text`, e.g. `[inventory-bootstrap-v1 import]`; do not pretend it was natural-language user input.
   - Commit only after all entities are created successfully. Any failure must roll back the complete bootstrap operation.

5. Add explicit preflight/dry-run and apply surfaces.
   - Provide a pure manifest validator and a database-aware preflight that confirms current schema plus empty inventory domain without mutation.
   - Add CLI commands and canonical Just recipes for dry-run/preflight and actual bootstrap apply.
   - Output concise machine-readable counts/format information consistent with existing storage/bootstrap CLI conventions.
   - Running dry-run/preflight must not create inventory rows, history events, or side effects.

6. Prove integration with current retrieval/recovery behavior.
   - After bootstrap apply, normal `SearchService` must find imported data by representative name/alias/tag/attribute/description queries and hierarchy paths.
   - Imported items must have the expected current locations/categories and exactly the normal creation-history semantics.
   - A normal `inventory-portable-v1` export of bootstrap-created state must remain valid; do not change portable-v1 schema or semantics.
   - Bootstrap must not create conversation, chat-request, evaluation, experiment, or provider records.

7. Add focused deterministic coverage.
   - Hand-authored `inventory-bootstrap-v1` fixture independent of application exporters.
   - Parser/semantic rejection cases for unknown format/fields, malformed paths, normalized path duplicates, missing parents, dangling item path refs, duplicate item identity, invalid state/quantity, and alias/tag duplicate/blank cases.
   - Preflight rejects non-current schema and any non-empty inventory domain without mutation.
   - Dry-run leaves the database unchanged.
   - Successful import covers nested locations/categories and multiple items with aliases/tags/attributes.
   - Transaction rollback test proves a mid-apply failure leaves the inventory domain empty.
   - Search/FTS and portable-export compatibility checks after successful bootstrap.

8. Update user-facing documentation only as needed to distinguish:
   - bootstrap onboarding import (`inventory-bootstrap-v1`) from
   - portable inventory/history recovery (`inventory-portable-v1`) and
   - full SQLite disaster-recovery backup/restore.
   - Do not mark Stage 16 complete.
   - Do not invent Stage 17. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- No merge/upsert into a non-empty inventory.
- No database schema migration for the bootstrap feature itself.
- No automatic application-startup migration.
- No change to `inventory-portable-v1`.
- No provider/model/network calls, prompt changes, embeddings, or live-provider verification.
- No voice/Telegram/images/QR/MCP/PWA/cloud/multi-user work.
- No dependency, runtime, or GitHub Actions version changes.
- No unrelated refactoring.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + self-review + focused verification + canonical verification + PR/CI correction + merge cycle.

Focused verification must include bootstrap validator/preflight/apply/rollback/search/portable-integration tests. Then run the complete protocol-v3 canonical verification set on the final implementation and after any task-related correction as required.

Create `agent-tasks/reviews/0005-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
