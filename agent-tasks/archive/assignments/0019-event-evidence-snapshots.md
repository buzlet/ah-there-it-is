# Assignment 0019: historical Event evidence snapshots

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/hardening-event-evidence-snapshots`

## Objective

Make newly-created Item Events retain truthful human-readable Location/Category path evidence from event time so later tree rename/reparent operations cannot retroactively change what the history appears to say.

## Required behavior

- Keep existing stable foreign-key IDs on `Event`; do not replace them with snapshots.
- Store new immutable path evidence inside the existing JSON `Event.payload` under one reserved key:

  `_history_evidence`

  with:

  ```json
  {
    "version": 1,
    "from_location_path": [{"location_id": 1, "name": "..."}, ...],
    "to_location_path": [{"location_id": 1, "name": "..."}, ...],
    "from_category_path": [{"category_id": 1, "name": "..."}, ...],
    "to_category_path": [{"category_id": 1, "name": "..."}, ...]
  }
  ```

- Omit path fields that are not relevant to an event. Path component order is root → leaf.
- Capture evidence at the mutation boundary:
  - `item_created`: current destination Location path when non-null and current Category path when non-null;
  - `item_moved`: both old and new Location paths as applicable;
  - `item_taken`: old Location path;
  - `item_updated` when Category changes: old and new Category paths as applicable.
- Snapshot components must be collected before the relevant relationship is changed.
- Ordinary Event payload semantics remain intact; the reserved key is additive.
- Old Events without `_history_evidence` remain valid. Do **not** backfill them from current paths.
- Portable-v1 export/import must preserve this payload unchanged. Add export → import → render/inspect coverage proving snapshot survival.
- Bootstrap-generated Events that flow through current service mutations should naturally receive current evidence; do not special-case or invent source-history evidence.
- Tree rename/reparent must not mutate prior Event payload snapshots.

## Coverage

At minimum:

- move after nested Location path creation then rename/reparent an ancestor; old Event snapshot remains original;
- create/take/move with null endpoints;
- category change followed by category ancestor rename/reparent;
- old Event without evidence remains readable;
- portable-v1 round trip preserves exact snapshot components;
- no extra Event is created merely to record a tree rename/reparent.

## Constraints

No relational schema migration, no Location/Category history subsystem, no backfill, no Activity UI, no lifecycle semantics, no delete/retirement, no provider/prompt/dependency/runtime/workflow changes.

## Focused verification

Run focused inventory/Event/tree/portable/bootstrap tests, then the canonical v4 verification set.
