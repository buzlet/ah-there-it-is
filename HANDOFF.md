# Session handoff

## Authoritative repository state

- Repository: `buzlet/ah-there-it-is`
- Default branch: `main`
- Always verify current `origin/main`, PR state, and CI before starting new work.
- This handoff supersedes the pre-Stage-12 handoff that existed at commit `198061c9c88353a950cb90f2ec8fcd6cabd51edf`.
- **Stages 0–12 are complete. Stage 13 is next.**
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

## Stage 13 objective

Freeze portable compatibility so future schema changes cannot silently invalidate existing `inventory-portable-v1` archives:

1. Add a hand-authored committed v1 fixture independent of the current exporter.
2. Keep an executable fixture -> validate -> import -> search -> re-export compatibility test across future schema migrations.
3. Treat `inventory-portable-v1` as immutable; incompatible changes require a new format ID and explicit version dispatch.
4. Test older `source.alembic_revision` metadata without executing or trusting source-schema implementation details.
5. Keep operational/evaluation/provider tables out of portable compatibility and in full SQLite backup.
6. Keep deferred product features out until this compatibility contract is protected.

## Files to read first

1. `HANDOFF.md`
2. `AGENTS.md`
3. `README.md`
4. `src/ah_there_it_is/storage.py`
5. `src/ah_there_it_is/storage_cli.py`
6. `tests/test_storage.py`
7. `migrations/env.py`
8. `src/ah_there_it_is/db/models.py`
9. `src/ah_there_it_is/services/search.py`
10. `Justfile`

## Orchestrated implementation workflow

Implementation-agent assignments are archived under `agent-tasks/`. Under this workflow the orchestrator owns repository verification and acceptance.

For an implementation handoff, the agent follows the referenced versioned common protocol, fast-forwards `main`, creates the assigned branch, implements only the assignment, opens a PR, and stops. It does not inspect unrelated branches/PRs/CI or run tests/checks unless the concrete assignment explicitly requests them. The orchestrator guarantees that no concurrent repository work occurs across the handoff interval.

The first archived assignment is `agent-tasks/assignments/0001-stage13-portable-compatibility.md`.

## Verification checkpoint

The orchestrator, not the implementation agent, verifies the resulting PR against current `main`, the assignment, canonical tests/checks, and CI before acceptance. Trust newer repository state over this handoff if they differ.
