# Assignment 0026: Stage 26 domain transitions and invariants

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 lifecycle.

Branch: `feat/stage26-location-truth-domain`

## Objective

Make InventoryService and domain history own all approved location-truth and terminal/reactivation transitions atomically.

## Required operations

### Move to known Location

`move_item(item_id, location_id)`

- `location_id` is non-null;
- result status `known`;
- terminal Items rejected;
- truthful no-op when already at that known Location.

### Take / in use

Add explicit `take_item(item_id)`.

- clear current Location;
- set `in_use`;
- Event `item_taken`;
- already-in-use is a truthful no-op.

### Mark location unknown

Add explicit `mark_item_location_unknown(item_id)`.

- clear current Location;
- set `unknown`;
- Event `item_location_unknown`;
- already-unknown is a truthful no-op.

### Terminal transitions

Add explicit service transitions for:
- discarded;
- sold.

Each transition atomically:
- sets the terminal ItemState;
- clears Location;
- sets `not_applicable`;
- records one authoritative Event (`item_discarded` / `item_sold`);
- rejects transition from another terminal state unless first reactivated.

### Reactivation

Add explicit reactivation of `sold`/`discarded`.

Caller must provide:
- a non-terminal target ItemState;
- required nullable Location ID:
  - explicit ID -> `known`;
  - explicit null -> `unknown`.

Do not infer prior state or Location. Direct reactivation to `in_use` is unsupported.

Record `item_reactivated`.

## Generic update/create behavior

- New non-terminal Item with Location -> `known`; without Location -> `unknown`.
- New terminal Item must have no Location and starts `not_applicable`.
- Generic `update_item` must not be a back door for entering/leaving terminal states; terminal transitions/reactivation use the explicit operations.
- Ordinary non-terminal state changes remain supported.

## Event evidence

For every operation that clears/sets a Location, preserve the historical path-evidence rules from Assignment 0019.

Terminal and reactivation Events must retain relevant from/to Location IDs and snapshots where applicable.

## Doctor

Extend doctor checks so contradictory location/status/terminal combinations are errors.

## Suggestions service

Enforce service-level eligibility:

- `known`: stored location authoritative, no inferred alternatives;
- `unknown`: suggestions allowed;
- `in_use`: suppress current-location suggestions;
- `not_applicable`: no suggestions.

## Receipts/no-op

All new mutations integrate with existing provisional/committed receipt semantics.

No-op transitions:
- `changed=false`;
- no new Event;
- no false changed receipt.

## Constraints

No agent tool schemas yet, no browser UX/filter changes, no duplicate/quantity work, no undo/delete, no retrieval/provider/dependency/workflow changes.

## Focused verification

Run InventoryService/Event/doctor/suggestion/receipt/portable-integration tests, then canonical verification.
