# Assignment 0012: Stage 23 browser activity timeline

Protocol: `agent-tasks/common/v4.md`

Branch: `feat/stage23-browser-activity`

## Objective

Expose the existing immutable Item event history as a practical, bounded browser audit surface.

## Required behavior

- Add `/activity` with newest-first deterministic pagination (50 default, 100 maximum), stable tie-breaking, and total/page metadata.
- Support filters for exact `event_type` and stable `item_id`; preserve filters across pagination and provide a clear/reset path.
- Add `/activity/{event_id}` showing event type/time, Item reference, from/to Location references, payload, and original text. Link surviving entities by stable ID and render nullable/missing optional references without failure.
- Put read/query/projection logic in an existing service/read boundary, not directly in route handlers. Do not load an unbounded Event collection.
- Add an Activity navigation entry. Existing Item detail history may link to Event detail, but its current semantics/order must remain unchanged.
- At representative large history volume, prove page-size/query work stays bounded structurally rather than by timing.
- Cover pagination/order/filter combinations, unknown Item/Event behavior, nullable references, navigation links, and installed-wheel assets when templates change.
- Update user documentation minimally.

## Constraints

Read-only stage. No schema/migration, Event generation changes, mutation/delete/retirement semantics, portable/bootstrap/backup/doctor changes, provider/prompt work, dependency/runtime/workflow upgrades, frontend framework, or unrelated refactoring.

## Focused verification

Run focused event/catalog/web/target-scale coverage, then the canonical v4 verification set.
