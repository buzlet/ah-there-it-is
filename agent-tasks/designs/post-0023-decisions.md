# Decisions after Assignment 0023

Date: 2026-09-24

## Retrieval

- Gating corpus: 86/86 pass.
- Existing intended ranking/normalization remains accepted.
- Measured defect: bounded candidate starvation with target FTS rank 36 outside the current pool of 20.
- Decision: fix candidate acquisition only; do not add fuzzy/transliteration/morphology/embeddings.
- Assignment 0024 delivered bounded FTS overscan (100–500 rows); the `blue box` rank-36 candidate is now a gating top-five success.
  Scoring, ordering and candidate sources remain unchanged.

## CI coverage

PR #42 measured 84% branch coverage:
- 6041 statements;
- 853 missed;
- 1516 branches;
- 293 partial branches.

Decision: keep report-only coverage for now. No `fail-under` yet.

## Stage 26 gates closed

Approved:
- portable-v2 with v1 import compatibility;
- explicit reactivation for sold/discarded with caller-selected non-terminal state and known/unknown location truth;
- terminal Items remain searchable;
- browser catalog defaults active-only with terminal/all filters;
- user-facing labels distinguish condition/state unknown from location unknown.

With these decisions encoded, Stage 26 implementation no longer requires a product-policy pause.


## Assignment 0025 delivery status

The approved location-truth storage and format slice is implemented:

- Item.location_status is persisted and constrained at the SQLite write boundary; old rows are backfilled conservatively, and ambiguous terminal rows with a stored Location stop migration before DDL.
- New creation and the existing location mutation path persist location truth atomically with the current Location.
- inventory-portable-v2 is the current export; frozen v1 remains importable with conservative status derivation and no new required v1 fields.
- Bootstrap-v1 structure is unchanged and applies known/unknown/not-applicable semantics without synthesizing in_use.
- Database doctor checks location truth.

Assignment 0025 did not change the closed Stage 26 product decisions and did not add take/unknown/sold/reactivation operations, agent tools, browser behavior, or suggestion policy.

## Assignment 0026 delivery status

The domain-transition and suggestion-eligibility slice is implemented:

- `move_item` now requires a known Location; `take_item` and `mark_item_location_unknown` set distinct location truth and Events.
- Explicit discard, sold, and reactivation operations update Item state, current Location, and `location_status` atomically, with one Event and path snapshots where applicable.
- Generic `update_item` cannot enter or leave terminal states; truthful no-op transitions create no Event and remain unchanged in mutation receipts.
- Location suggestions are available only for `unknown`; `known`, `in_use`, and `not_applicable` follow their approved eligibility rules.
- The delivered slice adds domain and receipt support without adding agent tool schemas or browser UX.

## Assignment 0027 delivery status

The provider-neutral agent contract now exposes Stage 26 location truth:

- `move_item` requires a resolved positive Location ID; `take_item`, `mark_item_location_unknown`, discard, sold, and reactivation are separate tools.
- Reactivation requires an explicit non-terminal state and required-nullable Location field; generic `update_item` schema excludes terminal states.
- Search, agent read/mutation, and catalog API item projections expose `state`, `current_location_id`, and `location_status`; terminal Items remain searchable.
- Deterministic corpus/scenarios cover the approved transitions, resolver gates, terminal rejection, malformed targets, reactivation, and truthful no-op receipts.
- No browser UX, duplicate/quantity, authentication/multi-user, or new search algorithm scope was added.

The broader Stage 26 remains in progress.
