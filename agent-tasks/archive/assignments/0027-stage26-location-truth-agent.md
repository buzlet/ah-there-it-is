# Assignment 0027: Stage 26 agent tool contract

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 lifecycle.

Branch: `feat/stage26-location-truth-agent`

## Objective

Expose Stage 26 semantics to the provider-neutral agent through explicit safe tools and deterministic scenarios without reintroducing nullable-move ambiguity.

## Tool contract

### move_item

- `location_id` becomes required and non-null/positive.
- Null is invalid.
- Existing strong Item/Location write-resolution and atomic revalidation rules remain mandatory.

### New explicit mutations

Expose provider-neutral tools for:
- `take_item(item_id)`;
- `mark_item_location_unknown(item_id)`;
- `discard_item(item_id)`;
- `mark_item_sold(item_id)`;
- `reactivate_item(item_id, state, location_id)`.

For reactivation:
- `state` must be non-terminal;
- `location_id` is required but nullable:
  - explicit null = reactivate as location unknown;
  - ID = reactivate at known Location;
- omitted location field is invalid.

## Authorization

- Existing Item IDs require the Stage 23 strong resolver/recheck.
- Location ID in move/reactivation requires strong Location resolution/recheck.
- Current-run created entities retain existing frozen-capability semantics.
- Search ranking, result count and weak evidence never authorize the new writes.

## Reads

Item/read/search/tool projections must expose:
- `state`;
- `current_location_id`;
- `location_status`.

Terminal state must be visible rather than filtered from agent search.

## update_item

Prevent generic agent `update_item` from entering/leaving terminal states. Prefer a schema-level non-terminal state vocabulary where practical, with service validation as the final authority.

## Provider schemas

Verify OpenAI-compatible and Gemini schema conversion for all new tools, including required-nullable reactivation Location.

## Deterministic scenarios

Add/adjust corpus + ScenarioLLMClient coverage for at least:

- known -> in_use -> known;
- known -> unknown -> known;
- unknown suggestion then explicit move;
- known -> discarded;
- known -> sold;
- sold/discarded -> explicit reactivation unknown;
- sold/discarded -> explicit reactivation known;
- terminal Item rejects move/take/unknown;
- omitted/null move target invalid;
- omitted reactivation location invalid vs explicit null valid;
- no-op transition receipts/events truthful.

Every scenario needs persisted-state postconditions.

## Constraints

No browser UX yet, no prompt/provider-specific tuning, no duplicate/quantity policy, no fuzzy/transliteration/morphology/embeddings, no dependency/runtime/workflow upgrades.

## Focused verification

Run dispatcher/resolver/provider-schema/scenario/receipt tests, then canonical verification.
