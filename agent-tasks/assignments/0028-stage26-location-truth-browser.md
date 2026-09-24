# Assignment 0028: Stage 26 browser UX and final integration

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 lifecycle.

Branch: `feat/stage26-location-truth-browser`

## Objective

Make the manual browser UI expose Stage 26 location truth and terminal lifecycle semantics explicitly, completing Stage 26 end-to-end.

## Item presentation

Show separately:

- Item condition/state;
- Location status.

User-facing labels must distinguish:
- condition/state unknown;
- location unknown.

Render:

- `known`: linked current Location;
- `unknown`: "Location unknown";
- `in_use`: "In use / taken from storage";
- `not_applicable`: terminal state, no current Location.

## Explicit manual actions

Do not use a blank Location form field as an ambiguous command.

Provide explicit actions/forms for:

- move to known Location;
- mark in use/taken;
- mark location unknown;
- mark discarded;
- mark sold;
- reactivate a terminal Item with explicit target non-terminal state and either known Location or location unknown.

Use InventoryService transitions only.

## Catalog/search filtering

Blank `/items` catalog:

- defaults to active Items;
- supports explicit active / terminal / all lifecycle filter;
- supports explicit location-unknown filter;
- preserves filters through pagination.

Nonblank browser search:

- remains capable of returning terminal Items by default;
- clearly displays terminal state and location status;
- lifecycle filter may narrow results when explicitly selected.

Do not make terminal Items disappear from memory/search merely because the default blank catalog is active-only.

## Suggestions UX

- show evidence-based location suggestions only for `unknown`;
- keep clear inference labeling;
- do not show current-location suggestions for `known`, `in_use`, or `not_applicable`.

## History/Activity integration

Activity and Item history must render the new Event types safely and retain historical path evidence.

Do not rewrite old Events.

## Scale/packaging/docs

Cover pagination/filter combinations at representative item volume and installed-wheel templates/assets.

Update README/AGENTS/HANDOFF factually to mark Stage 26 complete and describe the user-visible location truth model.

## End-to-end acceptance

Verify browser + API + agent/domain agreement for:
- known;
- unknown;
- in_use;
- discarded;
- sold;
- reactivation;
- terminal search visibility;
- active catalog default;
- unknown filter;
- suggestion eligibility.

## Constraints

No duplicate/quantity splitting, generic undo, hard delete, remote auth/multi-user, trace retention, backup scheduling, new retrieval algorithms, dependency/runtime/workflow upgrades.

## Focused verification

Run web/catalog/activity/suggestion/installed-wheel/end-to-end tests, then the full canonical verification set.
