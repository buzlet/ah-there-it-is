# Session handoff

## Authoritative repository state

- Repository: `buzlet/ah-there-it-is`
- Default branch: `main`
- Always verify current `origin/main`, PR state, and CI before starting new work.
- This handoff supersedes the pre-Stage-12 handoff that existed at commit `198061c9c88353a950cb90f2ec8fcd6cabd51edf`.
- **Stages 0–16 are complete. Stage 17 is next.**
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

## Stage 14 delivered

- packaged Alembic environment/revisions under `ah_there_it_is` with historical revision IDs unchanged;
- one explicit-URL packaged migration runner shared by operator upgrade/check flows and portable import;
- programmatic migrations immune to ambient active-database URL redirection;
- explicit upgrade/migration-check CLI and Just surfaces, with no startup auto-migration;
- source-development Alembic workflow retained against the packaged migration tree;
- migration package data included in the wheel;
- real wheel build/install smoke from outside the checkout proving fresh migration and portable-v1 import/search;
- complete protocol-v3 local verification and Python 3.12/3.13 CI green after one ordinary CI portability correction.

## Stage 15 delivered

- deterministic read-only location suggestions with typed evidence-bearing candidates;
- own-history `last_known` plus related-current-item evidence from shared category/tags;
- stable explainable ranking without fabricated probability/confidence;
- known current location remains authoritative and suppresses inferred alternatives;
- resolved-item-only suggestion tool; suggested locations become seen but never resolved merely by suggestion;
- replay capability reconstruction preserves the same authorization boundary;
- 42-case provider-independent corpus/scenario suite includes last-known and related-item suggestion flows with persisted-state/event no-mutation checks;
- no persistent suggestion state, schema/prompt/provider/runtime/dependency/workflow change, or portable/storage semantic change.

## Stage 16 delivered

- strict separate `inventory-bootstrap-v1` onboarding format with pure typed validation and explicit dispatch;
- component-array hierarchy paths and no imported IDs/history/timestamps/normalized/search/operational state;
- current-schema plus empty-inventory-domain preflight with operational state preserved;
- one-transaction apply through current `InventoryService`, generating current IDs/normalization/FTS/timestamps/item-created history with bootstrap provenance;
- no merge/upsert/overwrite/partial mode and no automatic active-database migration;
- explicit bootstrap preflight/apply CLI and Just surfaces;
- hand-authored fixture plus validator/preflight/dry-run/rollback/search/FTS/portable-v1 integration coverage;
- complete protocol-v3 verification green: 195 tests, 42/42 scenarios, provider contract, Python 3.12/3.13 CI.

## Stage 17 objective

Make the installed package directly runnable while keeping database lifecycle explicit:

1. Add an `ah-there-it-is serve` console entry point with `127.0.0.1:8000` defaults and explicit host/port overrides.
2. Remove module-level `app = create_app()` side effects; use `create_app()` as the Uvicorn factory and keep reload only in the development Just recipe.
3. Before installed serve, read-only verify that the configured database already exists and its Alembic head set exactly matches packaged heads; reject missing/behind/ahead schema without creating or migrating it.
4. Keep `storage_cli upgrade`, bootstrap, portable recovery, and backup/restore explicit and separate from startup.
5. Extend real wheel smoke coverage to run installed CLI/app outside checkout and verify localhost health/index/static assets.
6. Keep schema/data formats/provider/model/dependency/deployment-service concerns unchanged.

## Files to read first

1. `HANDOFF.md`
2. `AGENTS.md`
3. `README.md`
4. `pyproject.toml`
5. `src/ah_there_it_is/app.py`
6. `src/ah_there_it_is/config.py`
7. `src/ah_there_it_is/db/migrations/__init__.py`
8. `src/ah_there_it_is/db/session.py`
9. `src/ah_there_it_is/storage_cli.py`
10. `tests/test_app.py`
11. `tests/test_migrations.py`
12. `tests/test_wheel_migrations.py`
13. `Justfile`

## Orchestrated implementation workflow

Implementation-agent assignments and review records are archived under `agent-tasks/`. Current protocol v3 treats the trusted agent as both implementer and verifier.

For a normal implementation handoff, the agent fast-forwards `main`, implements only the assignment, self-reviews the complete diff, runs focused plus canonical local verification, opens the PR, waits for and diagnoses its own CI, applies task-related corrections, repeats until green, merges the PR, synchronizes local `main`, writes the compact review record required by the protocol, and returns only an aggregated summary. Raw test/Alembic/CI logs remain out of the orchestrator conversation unless needed to explain a blocker.

The orchestrator retains product/architecture direction, stage transitions, assignment formulation, and decisions where requirements conflict or a materially new design choice is needed. It does not repeat routine review/tests/CI already owned by the agent. The orchestrator guarantees that no concurrent repository work occurs between assignment publication and the agent's initial pull.

Assignment 0001 completed under v1. Assignment 0002/v2 was superseded before execution and is recorded in `agent-tasks/reviews/0002-r0.md`. Future implementation uses `agent-tasks/common/v3.md`; active Stage 17 work is `agent-tasks/assignments/0006-stage17-runtime-entrypoint.md`.

## Development environment checkpoint

Internal ChatGPT sandbox baseline relevant to project/build compatibility: Python 3.13.5, pip 25.1.1, setuptools 82.0.1, wheel 0.46.3; the separate `build` package is not installed.

U24 project venv at `/home/gpt/projects/ah-there-it-is/.venv` is aligned for the same build path where practical: Python 3.12.3 (project-supported), pip 25.1.1, setuptools 82.0.1, wheel 0.46.3, no `build` package. `python -m pip wheel --no-build-isolation --no-deps .` was verified successfully there. Do not upgrade these merely because newer versions or deprecation notices exist; the active sandbox remains the primary compatibility reference.
