# Assignment 0020: browser Activity timeline

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/browser-activity-timeline`

## Objective

Expose existing Item Event history as a practical bounded browser audit surface now that new Events carry truthful historical path evidence.

## Required behavior

- Add `/activity` with newest-first deterministic pagination:
  - default page size 50;
  - maximum 100;
  - stable order `created_at DESC, id DESC`;
  - total/page/pages/previous/next metadata.
- Support filters:
  - exact `event_type`;
  - stable `item_id`;
  - preserve filters through pagination;
  - clear/reset path.
- Add `/activity/{event_id}` showing:
  - stable Event ID;
  - event type/time;
  - surviving Item link when present;
  - from/to Location stable IDs/links when present;
  - payload;
  - original text.
- Historical path rendering:
  - when `_history_evidence` exists, render snapshot Location/Category path components as historical evidence;
  - for old Events without a snapshot, a surviving Location may be shown only as **current path; historical path unavailable**;
  - never present a current reconstructed path as if it were the path at event time.
- Put Event list/detail projection and pagination/filter query logic in a service/read boundary, not route handlers.
- Do not load an unbounded Event collection.
- Add Activity navigation entry.
- Existing bounded Item-detail history may link each Event to Activity detail without changing its established order/pagination semantics.
- Nullable/deleted Item references must render safely without inventing replacement identity.

## Scale/packaging coverage

- representative history volume >=1000 Events;
- structurally bounded page/query work, not timing thresholds;
- pagination/filter combinations and deterministic ties;
- unknown Item/Event handling;
- old vs new evidence rendering;
- navigation links;
- installed-wheel templates/static availability.

## Constraints

Read-only Activity stage. No Event-generation changes beyond merged 0019 behavior, no schema/migration, mutation/delete/lifecycle semantics, portable/bootstrap/backup/doctor/provider/prompt/dependency/runtime/workflow changes, frontend framework or unrelated refactor.

## Focused verification

Run focused Event/read/web/target-scale/installed-wheel tests, then the canonical v4 verification set.
