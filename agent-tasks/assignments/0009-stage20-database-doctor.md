# Assignment 0009: Stage 20 active database doctor

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage20-database-doctor`

## Objective

Add an installed, provider-independent health/consistency diagnostic for the active current-schema SQLite database that verifies application-level invariants beyond SQLite integrity/foreign keys. The default doctor is strictly read-only. Add one separate explicit repair operation only for derived FTS search state/schema, because it is fully reconstructible from authoritative inventory tables; never auto-repair authoritative domain/history data.

## Required implementation

1. Add a typed application database diagnostic boundary.
   - Introduce a small service/module that returns a structured doctor report with overall status, database path/revision, inventory counts, and per-check results.
   - Reuse existing SQLite/storage/migration helpers where appropriate instead of duplicating incompatible checks.
   - The doctor must require the configured file-backed SQLite database to exist and match the exact packaged/current Alembic head before running semantic checks.
   - Running the doctor must not create files/directories, mutate rows, install schema objects, rebuild indexes, checkpoint WAL, or otherwise change the database.

2. Include SQLite/schema checks already relied on by recovery.
   - `PRAGMA integrity_check` must be `ok`.
   - `PRAGMA foreign_key_check` must return no violations.
   - Database Alembic head set must exactly match packaged/current heads.
   - Normalize failures into the doctor report/CLI exit behavior rather than exposing raw tracebacks for ordinary diagnostic failures.

3. Validate current normalized identity state from authoritative rows.
   - Recompute `normalize_name()` and compare with persisted `normalized_name` for every Category, Location, Item, Alias, and Tag.
   - Detect duplicate normalized sibling category/location identities, including root-level duplicates where SQLite nullable uniqueness alone does not protect the semantic invariant.
   - Detect duplicate normalized item identity within the same category identity, including the null-category case, while respecting that intentionally allowed duplicate Items may already exist. Do not declare currently supported `allow_duplicate=True` items corrupt merely because names collide.
   - Therefore report duplicate Item identities separately as an informational/warning count unless another invariant is violated; do not make them a fatal doctor failure.
   - Alias-per-item and global-tag normalized uniqueness should still be checked semantically even where database constraints normally enforce them.

4. Validate hierarchy/domain scalar invariants.
   - Detect category and location parent cycles deterministically.
   - Validate every item state against current `ItemState`.
   - Validate item quantity >= 1.
   - Validate non-blank authoritative names and alias/tag names according to current service/domain rules.
   - Do not invent stricter historical rules for event payloads or free-form descriptions.

5. Validate derived FTS schema and content.
   - Verify the expected `item_search_fts` virtual table and the current expected trigger set exist.
   - Compare FTS rows with authoritative Item/Alias/Tag/attribute/description state using one reusable consistency function; include missing, mismatched, and extra row IDs in a bounded diagnostic result rather than dumping an unbounded list.
   - Refactor the existing portable-import-only FTS consistency logic into a reusable boundary so portable import and doctor cannot silently diverge.
   - FTS mismatch or missing FTS schema objects is a doctor failure, but it must not mutate anything.

6. Add installed `ah-there-it-is doctor`.
   - Read the effective database from normal Settings/data-home precedence.
   - Print concise machine-readable JSON with `ok`, database/schema metadata, counts, and named check summaries.
   - Return exit code 0 only when all fatal checks pass; return a stable nonzero diagnostic exit code for an unhealthy/missing/incompatible database.
   - Warnings such as intentional duplicate item identities must be represented explicitly and must not force failure.
   - Never print provider keys/secrets.

7. Add a separate explicit `ah-there-it-is repair-search-index` operation.
   - This command may modify only derived FTS table/trigger/index state. It must not change categories, locations, items, aliases, tags, item_tags, events, conversations, chat requests, evaluation/experiment/provider state, timestamps, or Alembic revision.
   - Before repair, require an existing database at exact current schema and require all non-FTS fatal doctor checks to pass. If authoritative/base invariants are unhealthy, refuse repair.
   - In one explicit transaction, install/restore the expected current FTS objects if missing and rebuild FTS content from authoritative rows using the existing search-schema functions.
   - After repair, rerun the complete doctor and return success only if it is healthy.
   - Keep repair idempotent: running it against already-correct FTS state must preserve authoritative data and result in a healthy database.
   - Do not make `serve`, `doctor`, migration, bootstrap, restore, or startup invoke this repair automatically.

8. Add deterministic corruption/repair coverage.
   - Healthy current-schema inventory passes doctor, including the 1000-item target-scale fixture or an equivalent representative fixture where practical.
   - Directly corrupt one persisted normalized name and prove doctor detects it read-only.
   - Construct category/location cycle corruption in a controlled test database and prove detection without hanging.
   - Corrupt invalid state/quantity in direct SQL and prove detection.
   - Corrupt/delete/add FTS rows and drop one expected FTS trigger; doctor must detect each class without modifying the database.
   - `repair-search-index` repairs only FTS corruption/missing FTS objects and leaves a before/after snapshot of all authoritative/base tables semantically identical.
   - `repair-search-index` refuses to run when a base invariant is corrupt.
   - Doctor against a missing/outdated database must not create/upgrade it.

9. Preserve recovery/runtime contracts.
   - Do not change `validate_database()` semantics used by backup/restore unless extracting a shared read-only helper without weakening its current contract.
   - Do not alter backup/restore, bootstrap-v1, portable-v1, runtime schema gate, or startup migration behavior.
   - Portable import must continue validating reconstructed FTS state through the new shared consistency boundary.

10. Update documentation only as needed.
   - Document `ah-there-it-is doctor` as the read-only installed health check and `repair-search-index` as an explicit derived-state repair.
   - State clearly that doctor does not repair domain data and repair-search-index cannot repair inventory/history corruption.
   - Do not mark Stage 20 complete.
   - Do not invent Stage 21. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- No database schema/Alembic migration in this stage.
- No automatic repair of authoritative inventory/history rows.
- No general-purpose SQL console or arbitrary repair framework.
- No change to stable IDs/history semantics or allowed duplicate-item behavior.
- No provider/model/network calls, embeddings, prompt changes, or live-provider verification.
- No new dependency solely for diagnostics.
- No systemd/service-manager, Docker/container, installer packaging, TLS, auth, cloud, multi-user, PWA, voice, Telegram, images, QR, or MCP work.
- No dependency/runtime/GitHub Actions upgrades and no unrelated refactoring.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + self-review + focused verification + canonical verification + PR/CI correction + merge cycle.

Focused verification must include healthy/corrupt doctor cases, read-only/no-create guarantees, FTS schema/content corruption, explicit FTS repair/idempotency/base-table preservation, repair refusal on authoritative corruption, and portable-import shared FTS consistency coverage. Then run the complete protocol-v3 canonical verification set on the final implementation and after any task-related correction as required.

Create `agent-tasks/reviews/0009-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
