# Assignment 0008: Stage 19 target-scale read-path readiness

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage19-target-scale-read-paths`

## Objective

Validate and harden the deterministic read paths at the product's intended local scale: about 1000 items and 100–250 nested locations. Remove the known full-inventory/N+1 read patterns without changing search semantics or introducing brittle wall-clock performance gates. Structural bounded-work guarantees, not timing on shared CI hardware, are the acceptance criterion.

## Required implementation

1. Add a deterministic target-scale test fixture/generator.
   - Build exactly 1000 items, about 200 nested locations, and a representative nested category tree using current domain services in one controlled transaction.
   - Include deterministic aliases, tags, structured attributes, descriptions, duplicate leaf location names under different ancestry, and a small set of intentionally unknown-location items.
   - Include named target records for exact-name, exact-alias, exact-attribute, exact-tag, FTS-description, ambiguity/path, and location-suggestion assertions.
   - Do not commit a giant generated JSON database/export. Keep the fixture as compact deterministic test code/data and use no stochastic generator unless a fixed deterministic seed is part of the contract.
   - This scale fixture is test infrastructure only, not a production bootstrap format or demo dataset.

2. Remove full-inventory ORM materialization from `SearchService.search_items()`.
   - Preserve the existing public result DTOs, ranking constants, deterministic tie ordering, query normalization, FTS punctuation safety, and observable semantics covered by current search/corpus/scenario tests.
   - Candidate discovery must be SQL/FTS-first and bounded relative to the requested result limit; do not load every `Item` plus every alias/tag merely to decide which handful of candidates to return.
   - Exact name/alias/tag candidates must continue to receive their existing ranking even when FTS also matches.
   - Exact structured-attribute and normalized/contains behavior must remain observable as today; it is acceptable to use FTS/SQL to obtain a bounded candidate set and then apply the existing Python ranking rules only to those candidates.
   - Load aliases/tags/context only for candidate items needed to rank/render the final bounded set.
   - A scale regression test must fail if a limit-5 search on the 1000-item fixture regresses to materializing essentially the whole item table. Use SQLAlchemy load/query instrumentation or an equivalently structural assertion; do not assert elapsed milliseconds.

3. Restrict location-suggestion evidence queries to relevant rows.
   - `LocationSuggestionService` must not materialize all items with known locations before checking category/tags.
   - Query only rows that can contribute evidence: same category and/or at least one shared target tag, plus the target item's own history.
   - Prefer selecting/aggregating only the columns needed for evidence rather than hydrating unrelated Item graphs.
   - Preserve Stage 15 ranking, evidence payload, supporting-item IDs, last-known semantics, seen-not-resolved authorization, and read-only behavior exactly.
   - Add scale coverage with many unrelated items proving they do not become ORM-loaded evidence candidates.

4. Add the one index needed for reverse tag membership lookup.
   - Add model metadata plus one Alembic migration for an index on `item_tags.tag_id` (name it consistently, e.g. `ix_item_tags_tag_id`).
   - Do not alter historical migration files or other schema semantics.
   - Migration upgrade/downgrade and autogenerate/check behavior must remain green.

5. Bound the web item catalog.
   - Add a paged catalog service projection for items with a deterministic default page size of 50 and a hard maximum of 100.
   - `/items` must use the paged projection rather than rendering all inventory items.
   - Return/render total item count and enough page metadata for deterministic previous/next navigation.
   - Invalid page/page-size values must fail clearly or be normalized by one documented policy; do not silently request unbounded pages.
   - Preserve item ordering by normalized name then stable ID.
   - Keep item detail behavior and manual correction semantics unchanged.

6. Remove location/category count N+1 behavior.
   - `CatalogService.list_locations()` and `list_categories()` must compute direct item counts with grouped SQL aggregation or an equivalent bounded-query strategy rather than `len(node.items)` lazy loads per node.
   - Full listing of roughly 200 tree nodes is acceptable in this stage; the requirement is bounded SQL query count independent of node count, not tree pagination.
   - Preserve full ancestry paths and direct-item-count semantics.

7. Add target-scale structural regression coverage.
   - On the 1000-item fixture, prove representative exact-name, alias, attribute, tag, description/FTS, and deterministic tie searches still return the intended candidates.
   - Prove search candidate/entity loading is materially bounded below the total inventory for normal limit-5 queries.
   - Prove location suggestions ignore the large unrelated population while preserving expected evidence/ranking.
   - Prove item page 1 contains at most 50 items, reports total=1000, and a later page returns the correct deterministic next slice; web HTML must not render off-page items.
   - Prove location/category listing query counts do not grow one statement per node.
   - Keep these assertions structural. Do not add pass/fail latency thresholds, CPU thresholds, or benchmark numbers that vary with CI host load.

8. Preserve provider-independent application behavior.
   - The existing 42-case corpus/scenario suite and all state/event postconditions must remain unchanged unless a route-only catalog test needs new page metadata.
   - No provider/model calls, embeddings, prompt tuning, or live-provider verification are part of this stage.
   - Search optimizations must remain deterministic and must not move ranking decisions into the LLM.

9. Update documentation only as needed.
   - Record that the core read paths are exercised at the intended ~1000-item / ~200-location scale and that catalog item listing is paged.
   - Do not publish synthetic timing claims.
   - Do not mark Stage 19 complete.
   - Do not invent Stage 20. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- Exactly one narrowly justified schema change: the `item_tags.tag_id` lookup index.
- No change to inventory-bootstrap-v1, inventory-portable-v1, backup/restore semantics, or stable identity/history rules.
- No embeddings, external search engine, cache server, async database conversion, ORM replacement, or new persistence service.
- No frontend framework or broad UI redesign.
- No provider/model/network API changes or live-provider work.
- No systemd/service-manager, Docker/container, installer packaging, TLS, auth, cloud, multi-user, PWA, voice, Telegram, images, QR, or MCP work.
- No dependency/runtime/GitHub Actions upgrades and no unrelated refactoring.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + self-review + focused verification + canonical verification + PR/CI correction + merge cycle.

Focused verification must include the target-scale fixture, bounded search/suggestion loading assertions, catalog pagination, bounded location/category count queries, and migration upgrade/downgrade/check coverage. Then run the complete protocol-v3 canonical verification set on the final implementation and after any task-related correction as required.

Create `agent-tasks/reviews/0008-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
