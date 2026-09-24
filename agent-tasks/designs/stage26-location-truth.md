# Stage 26 design: location truth semantics

Status: **approved design, not yet implemented**

This document defines the product/domain semantics for the deferred Stage 26. It intentionally does not cover duplicate-instance/quantity policy.

## Problem

Today `Item.current_location_id = NULL` carries multiple meanings:

- the location is unknown;
- the item was intentionally taken out of storage / is in use;
- the item is no longer physically tracked (for example discarded);
- historical data may simply never have had a location.

That ambiguity leaks into manual UI, suggestions, agent tools and history.

`ItemState` already exists and mixes physical condition/lifecycle values such as `working`, `broken`, `for_sale` and `discarded`. Stage 26 must not create a second competing general lifecycle scale.

## Decision

Add one orthogonal field concerned **only with location truth**:

`location_status`

with controlled values:

- `known`
- `unknown`
- `in_use`
- `not_applicable`

This field answers only: **what does the current-location state mean?**

It does not replace `ItemState`.

### Meaning

#### known

The current physical location is known and represented by `current_location_id`.

Invariant:

`location_status == known` iff `current_location_id IS NOT NULL`.

#### unknown

The item is still tracked/owned but its current physical location is unknown.

Invariant:

- `current_location_id IS NULL`;
- location suggestions may be shown as evidence, clearly labelled as inference rather than truth.

#### in_use

The item was intentionally taken from storage / is currently with the user or otherwise intentionally outside a stored Location.

Invariant:

- `current_location_id IS NULL`;
- historical storage locations remain history only;
- ordinary "where might it be stored?" suggestions must not be presented as probable **current** locations.

This replaces the old ambiguity where `item_taken` and a generic null location shared the same persistent representation.

#### not_applicable

The item is no longer physically tracked in the active inventory.

Invariant:

- `current_location_id IS NULL`;
- this status is permitted only for terminal/non-possessed Item states defined below.

## ItemState interaction

Keep the existing `ItemState` field. Add:

- `sold`

to the controlled vocabulary.

Stage 26 treats:

- `discarded`
- `sold`

as terminal/non-possessed states.

Invariants:

- `state in {discarded, sold}` requires `location_status == not_applicable`;
- `location_status == not_applicable` requires `state in {discarded, sold}`;
- terminal/non-possessed Items cannot have `current_location_id`;
- all other ItemState values must use `known`, `unknown`, or `in_use`.

`for_sale` is **not** terminal. A for-sale Item can still be located, unknown, or temporarily in use.

This intentionally preserves the current mixed ItemState vocabulary rather than introducing a second ownership-state column in Stage 26.

## Migration of existing data

Migration must be conservative and must not infer intent from historical Events.

For existing rows:

1. `current_location_id IS NOT NULL` → `location_status = known`.
2. `current_location_id IS NULL AND state = discarded` → `location_status = not_applicable`.
3. every other existing `current_location_id IS NULL` → `location_status = unknown`.

Do **not** convert an old null row to `in_use` merely because the latest Event is `item_taken`. Historical `item_taken` was created under ambiguous semantics and is not sufficient evidence.

Existing rows cannot be `sold` before the new vocabulary exists.

## Explicit mutation operations

After Stage 26 there must be no generic "set location to null and guess what it means" write.

### Move to known location

`move_item(item_id, location_id)`

- `location_id` is required and non-null;
- result: `location_status = known`;
- event: `item_moved`.

### Take / mark in use

Use an explicit operation such as:

`take_item(item_id)`

- result: `current_location_id = NULL`;
- `location_status = in_use`;
- event: `item_taken`.

The agent tool surface should use this explicit operation rather than nullable `move_item.location_id`.

### Mark location unknown

Use an explicit operation such as:

`mark_item_location_unknown(item_id)`

- result: `current_location_id = NULL`;
- `location_status = unknown`;
- event: `item_location_unknown`.

This is distinct from taking the item.

### Terminal state transition

Changing an Item to `discarded` or `sold` must be atomic:

- set terminal state;
- clear `current_location_id`;
- set `location_status = not_applicable`;
- record one authoritative domain mutation/event.

The implementation may use explicit `discard_item` / `mark_item_sold` operations or an invariant-owning service transition, but it must not temporarily commit contradictory combinations.

Moving a terminal Item to a Location, taking it, or marking its location unknown must fail until the Item first returns to a non-terminal state through an explicit supported transition.

## Creation semantics

For a new non-terminal Item:

- with an explicit Location → `known`;
- without a Location → `unknown`.

Creating an Item directly in a terminal state is allowed only if the service creates it with:

- no Location;
- `location_status = not_applicable`.

No default creation path should produce `in_use`; that state expresses an explicit action.

## Manual browser behavior

The browser must stop using a blank Location field as an ambiguous command.

Item detail/edit should expose current location truth clearly:

- Known: show/link Location.
- Unknown: show "Location unknown".
- In use: show "In use / taken from storage".
- Not applicable: show terminal state and no current Location.

Manual actions should be explicit:

- move to Location;
- mark location unknown;
- mark in use/taken;
- terminal transition where supported.

Add an `unknown location` catalog filter.

Location suggestions/evidence may be shown for `unknown` Items. They must remain clearly labelled inference.

Do not show storage suggestions as probable current locations for `in_use` or `not_applicable` Items.

## Agent behavior

Agent mutation tools must mirror the explicit domain operations.

The agent must never convert a missing/omitted Location argument into a state transition.

Expected tool distinction:

- `move_item(item_id, location_id)`
- `take_item(item_id)`
- `mark_item_location_unknown(item_id)`

Terminal transitions must also be explicit and subject to the same resolved-target/write-safety rules established by Stage 23.

Read tools should expose both:

- `current_location_id`;
- `location_status`.

The model should not infer one from the other.

## Suggestions

LocationSuggestionService policy:

- `known`: stored location is authoritative; do not present alternatives as current.
- `unknown`: evidence-based suggestions allowed.
- `in_use`: suppress ordinary current-location suggestions.
- `not_applicable`: no suggestions.

A future "likely return/storage location" feature for an in-use Item would be a different product concept and is not part of Stage 26.

## History / Events

Stage 26 does not rewrite old Events.

New Events must truthfully distinguish:

- moved to known Location;
- taken/in use;
- location marked unknown;
- terminal disposal/sale transition.

Historical evidence snapshots from Assignment 0019 remain additive and separate from current location truth.

## Portable/bootstrap/full backup

- Full SQLite backup naturally preserves the new column.
- Portable format must preserve `location_status` and the extended ItemState vocabulary. If frozen `inventory-portable-v1` cannot be changed compatibly, introduce the smallest explicit version evolution rather than silently dropping the field.
- Bootstrap format should keep onboarding semantics simple:
  - supplied location → known;
  - no supplied location → unknown;
  - it should not synthesize in-use intent.
- Old portable/bootstrap fixtures remain compatibility tests.

## Doctor invariants

Database doctor should treat as errors:

- `known` + null Location;
- non-`known` + non-null Location;
- `not_applicable` + non-terminal ItemState;
- terminal ItemState + any status except `not_applicable`.

## Explicit non-goals

Stage 26 does not decide:

- duplicate physical-instance UX;
- quantity splitting;
- hard delete;
- archive/retirement beyond sold/discarded terminal states;
- undo as destructive history editing;
- fuzzy search/transliteration/embeddings;
- multi-user possession semantics.

## Acceptance shape

A future Stage 26 implementation assignment should cover, at minimum:

- schema migration and conservative backfill;
- domain invariants and explicit transitions;
- agent schemas/tools;
- manual browser actions and unknown filter;
- suggestion eligibility;
- doctor;
- portable/bootstrap compatibility;
- deterministic scenarios for known → in_use → known, known → unknown → known, known → sold/discarded, and invalid contradictory combinations.


## Closed decision gates after Assignment 0023

These decisions are now **approved** and remove the remaining product ambiguity before Stage 26 implementation.

### Portable format evolution

Adopt `inventory-portable-v2`.

Rules:

- current Stage 26-capable databases export as v2;
- v1 remains a supported import format;
- v1 import derives `location_status` conservatively:
  - non-null location -> `known`;
  - null + `discarded` -> `not_applicable`;
  - all other null -> `unknown`;
- new Stage 26 semantics must never be exported as v1 because that would discard meaning;
- v2 carries `location_status` and the extended ItemState vocabulary explicitly.

### Reactivation of terminal Items

Both `sold` and `discarded` are reversible only through an explicit correction/reactivation operation.

The reactivation request must explicitly choose:

- a non-terminal ItemState;
- either:
  - a known Location ID, yielding `location_status=known`; or
  - no Location, yielding `location_status=unknown`.

Reactivation must not infer the previous non-terminal state or previous Location.

Direct reactivation into `in_use` is not supported. Reactivate first, then use the explicit take/in-use operation.

Every reactivation creates immutable domain history.

### Visibility of terminal Items

Terminal Items remain searchable by default.

Reason: the product is a memory system, so "sold" or "discarded" is a useful answer to "where/what happened to X".

Browser catalog behavior:

- default view: active Items only;
- explicit filter: terminal only;
- explicit filter: all Items.

Agent/read search results include terminal state clearly.

Storage/location mutation tools must reject terminal Items until they are explicitly reactivated.

### UI naming for the two unknown concepts

Keep the internal enum names unchanged.

User-facing labels must distinguish:

- Item state `unknown` -> **Condition/state unknown**;
- `location_status=unknown` -> **Location unknown**.

API/schema documentation must preserve the same distinction.

### Coverage policy after first baseline

First CI branch-coverage baseline from PR #42:

- statements: 6041;
- missed statements: 853;
- branches: 1516;
- partial branches: 293;
- total branch coverage: **84%**.

Coverage remains **report-only** for now.

Do not add a `fail-under` threshold until multiple representative implementation PRs establish a stable baseline. Coverage must remain CI-only; no local/project dependency is added merely to collect it.

### Retrieval decision after Assignment 0023

The gating retrieval corpus passes 86/86 with current SearchService semantics.

Measured unsupported observations:

- typo;
- RU transliteration;
- UK inflection.

These remain non-requirements.

One real bounded-candidate starvation case was measured:

- query: `blue box`;
- intended target FTS rank: 36;
- current bounded candidate pool: 20;
- target absent from the returned top five.

The next search change is therefore limited to correcting bounded candidate starvation while preserving existing ranking semantics.

Do not introduce fuzzy matching, transliteration, stemming/morphology, embeddings or vector search as part of that fix.
