# Assignment 0016: bounded high-cardinality read surfaces

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/hardening-bounded-reads`

## Objective

Remove remaining unbounded request/tool reads for Item history and Location contents without changing inventory semantics.

This is a maintenance assignment and does not consume/redefine product Stage 26.

## Required behavior

- Add bounded service projections for:
  - Item Event history;
  - direct Items in a Location.
- Use deterministic page-based pagination: default page size 50, maximum 100, positive page/page-size validation, total/pages/previous/next metadata.
- Preserve existing ordering semantics:
  - Item history by `created_at ASC, id ASC`;
  - Location contents by stable Item ID unless an existing stronger documented order applies.
- Change agent `get_item_history` and `list_location` tools to accept bounded pagination inputs and return page objects rather than unbounded arrays.
- Only Items returned in the current Location page become newly `seen`; pagination must not grant capabilities for rows not returned.
- Bound the Item-detail browser history path as well. Item core detail must not materialize the full Event collection. Preserve the current default history order and provide clear pagination links.
- Reuse a read/service boundary for count/page queries; do not put bulk query assembly directly into route handlers.
- If an internal unbounded helper remains for non-request code, ensure web/agent request paths do not call it.

## Scale coverage

At representative high cardinality:

- one Item with at least 1000 Events;
- one Location with several hundred direct Items;

prove structurally that one request/tool call materializes only the requested page and uses bounded query work. Do not use timing thresholds.

Cover invalid page/page-size, out-of-range pages, stable tie/order behavior, navigation links and installed-wheel templates/tool schemas as applicable.

## Constraints

Do not introduce conversation summarization/window policy, cursor infrastructure, schema migration, search/ranking changes, mutation semantics, provider changes, frontend framework, dependency/runtime/workflow upgrades or unrelated refactoring.

## Focused verification

Run focused inventory/catalog/tool/web/target-scale tests, then the canonical v4 verification set.
