# Session handoff

## Authoritative repository state

- Repository: `buzlet/ah-there-it-is`
- Default branch: `main`
- Always verify current `origin/main`, PR state, and CI before starting new work.
- This handoff supersedes the pre-Stage-12 handoff that existed at commit `198061c9c88353a950cb90f2ec8fcd6cabd51edf`.
- **Stages 0–13 are complete. Stage 14 is next.**
- `AGENTS.md` remains the authoritative architecture/development/stage plan.
- Full SQLite backup/restore and portable inventory import are intentionally separate recovery products.

## Stage 12 delivered

- strict `inventory-portable-v1` parser/validator with explicit format and unknown-field rejection;
- duplicate JSON object-key detection and structural validation errors;
- pure pre-write validation of duplicate IDs, all category/location/item/event references, self-parent links, hierarchy cycles, duplicate normalized sibling names, item state/quantity/timestamps, aliases, and tags;
- dry-run CLI validation with no destination database creation;
- import only to a new output path, never merge/overwrite and never the configured active database;
- Alembic migration of a private staging database with an explicit URL override immune to ambient `AH_THERE_IT_IS_DATABASE_URL`;
- stable category/location/item/event IDs and audit timestamps preserved;
- category/location trees, items, aliases, tags, attributes, current locations, and domain history reconstructed;
- normalized fields recomputed with current code instead of accepted from JSON;
- FTS rebuilt by current SQLite triggers and checked against reconstructed base tables;
- WAL-safe staged consolidation through SQLite's backup API plus atomic no-overwrite publication;
- semantic `export -> import -> export` and deterministic SearchService/FTS coverage;
- conversations, chat-request idempotency/recovery records, evaluation/model/provider traces remain excluded from portable reconstruction and available through full SQLite backup only;
- canonical Just recipes: `portable-import-dry-run` and `portable-import`.

## Important invariants

- The LLM never accesses or writes the database directly.
- Domain/service code owns normal application mutations and transaction boundaries.
- Existing application mutations use stable IDs and retain auditable item history.
- Agent turns remain transactionally atomic.
- Normal application CI remains provider/model independent.
- Portable import validates completely before database creation.
- Portable import has no merge mode and no overwrite mode.
- Portable input never supplies trusted normalized/FTS state.
- Full SQLite backup/restore remains the disaster-recovery mechanism for all application tables.

## Stage 13 delivered

- committed hand-authored `inventory-portable-v1` fixture using older revision `c4cfe3a3e921`;
- executable fixture -> validate -> current-schema import -> SearchService -> re-export compatibility coverage;
- semantic preservation of portable IDs, timestamps, hierarchy, items, aliases/tags, attributes, current references, and domain history;
- explicit format-version parser dispatch with frozen v1 behavior and clear unsupported-format rejection;
- old source revision treated only as metadata while current migrations/schema/domain invariants own reconstruction;
- portable/full-backup separation preserved.

## Stage 14 objective

Remove the source-checkout/current-working-directory dependency from runtime migrations:

1. Package the existing Alembic environment/revision files with `ah_there_it_is`.
2. Build one programmatic migration configuration/runner from packaged resources and an explicit database URL.
3. Make portable import work outside the repository without `alembic.ini` in the current directory.
4. Add an explicit database-upgrade operation plus minimal CLI/Just entry point, with no automatic migration during application startup.
5. Test fresh upgrade and v1 compatibility import/search from an unrelated temporary working directory.
6. Keep sandbox-compatible dependency/tool versions and avoid provider/model/deferred-product scope.

## Files to read first

1. `HANDOFF.md`
2. `AGENTS.md`
3. `README.md`
4. `pyproject.toml`
5. `migrations/env.py`
6. `src/ah_there_it_is/storage.py`
7. `src/ah_there_it_is/storage_cli.py`
8. `tests/test_migrations.py`
9. `tests/test_storage.py`
10. `tests/test_portable_compatibility.py`
11. `Justfile`

## Orchestrated implementation workflow

Implementation-agent assignments are archived under `agent-tasks/`. Under this workflow the orchestrator owns repository verification and acceptance.

For an implementation handoff, the agent follows the referenced versioned common protocol, fast-forwards `main`, creates the assigned branch, implements only the assignment, opens a PR, and stops. It does not inspect unrelated branches/PRs/CI or run tests/checks unless the concrete assignment explicitly requests them. The orchestrator guarantees that no concurrent repository work occurs across the handoff interval.

The assignment/review archive now includes completed Assignment 0001 plus `agent-tasks/reviews/0001-r1.md`. Future implementation work uses `agent-tasks/common/v2.md`; Stage 14 is `agent-tasks/assignments/0002-stage14-packaged-migrations.md`.

## Verification checkpoint

The orchestrator, not the implementation agent, verifies the resulting PR against current `main`, the assignment, canonical tests/checks, and CI before acceptance. Trust newer repository state over this handoff if they differ.
