# Assignment 0025: Stage 26 location-truth storage model and portable-v2

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 lifecycle.

Branch: `feat/stage26-location-truth-storage`

## Objective

Introduce the persistent location-truth model, conservative migration, and lossless portable-v2 compatibility defined by the approved Stage 26 design.

## Required model

Add controlled `location_status` values:

- `known`
- `unknown`
- `in_use`
- `not_applicable`

Add `sold` to `ItemState`.

Persist `Item.location_status` as non-null authoritative state.

## Database invariants

Enforce at the database/schema boundary as well as application code:

- `known` requires non-null `current_location_id`;
- every non-`known` status requires null `current_location_id`;
- `discarded` and `sold` require `not_applicable`;
- `not_applicable` requires `discarded` or `sold`;
- non-terminal Item states cannot use `not_applicable`.

Use packaged Alembic migration(s), not startup repair.

## Conservative migration

Existing rows map exactly:

1. non-null current Location -> `known`;
2. null Location + `discarded` -> `not_applicable`;
3. every other null Location -> `unknown`.

Do not infer `in_use` from old `item_taken` Events.

## Portable-v2

Introduce `inventory-portable-v2`.

- Current export emits v2.
- V2 Item records explicitly preserve `location_status` and the extended ItemState vocabulary.
- Continue importing frozen v1 and new v2.
- Frozen v1 structure/validation must not silently acquire new required fields.
- V1 import derives location truth using the same conservative migration mapping.
- New Stage 26 data must never be exported as v1.
- V2 export -> import -> export preserves stable IDs/timestamps/history and location truth.
- Historical Event payload evidence from Assignment 0019 remains byte/semantic preserving through portable round trip.

## Bootstrap-v1 compatibility

Keep the existing bootstrap structure.

On apply:
- non-terminal + supplied Location -> `known`;
- non-terminal + no Location -> `unknown`;
- terminal state + no Location -> `not_applicable`;
- terminal state + supplied Location -> validation failure.

Bootstrap must never synthesize `in_use`.

## Scope boundary

This assignment establishes storage/format semantics only. Do not yet add take/unknown/sold/reactivate service operations, agent tools, browser actions/filters, or suggestion policy changes.

## Focused verification

Run migration/backfill/schema-constraint/portable-v1+v2/bootstrap/installed-wheel tests, then canonical verification.
