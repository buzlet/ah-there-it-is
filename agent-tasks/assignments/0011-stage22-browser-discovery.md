# Assignment 0011: Stage 22 deterministic browser discovery

Protocol: `agent-tasks/common/v4.md`

Branch: `feat/stage22-browser-discovery`

## Objective

Make the manual browser useful at the intended inventory scale without relying on chat or adding a second search implementation.

## Required behavior

- Add Item search to `/items` via a query parameter and reuse `SearchService.search_items()` exactly for ranking/FTS semantics. Blank query must preserve the existing Stage 19 paged catalog.
- Keep browser search bounded (maximum 100 results), preserve deterministic order/stable IDs, display the active query and a clear/reset path, and link every result to its Item detail. Do not claim a total count when results are intentionally capped.
- Add read-only `/locations/{id}` and `/categories/{id}` detail pages with full path, parent link, child links, description, and **direct** Items. Do not recursively hydrate an entire subtree.
- Cross-link Item list/detail category and location paths to those stable-ID tree detail pages. Existing create/edit routes remain separate.
- Put read projections/query assembly in `CatalogService` or another existing read boundary; keep route handlers thin.
- At the 1000-item / 200-location fixture, prove normal browser search and tree detail reads remain structurally bounded and do not regress to loading the full Item table.
- Cover name/alias/tag/attribute/description search through the browser, blank-query pagination, duplicate leaf tree paths, direct-item membership, navigation links, 404s, and installed-wheel assets if new templates/static files are added.
- Update user documentation minimally to describe deterministic browser search/navigation.

## Constraints

No schema migration, new search/ranking semantics, embeddings/external search, mutation/delete behavior, provider/prompt changes, frontend framework, dependency/runtime/workflow upgrades, or unrelated refactoring.

## Focused verification

Run the focused browser/search/catalog/target-scale coverage required by this assignment, then the canonical v4 verification set.
