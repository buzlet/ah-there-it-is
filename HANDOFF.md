# Session handoff

## Authoritative repository state

- Repository: `buzlet/ah-there-it-is`
- Default branch: `main`
- Always verify current `origin/main`, PR state, and CI before starting new work.
- This handoff supersedes the pre-Stage-12 handoff that existed at commit `198061c9c88353a950cb90f2ec8fcd6cabd51edf`.
- **Stages 0–14 are complete. Stage 15 is next.**
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

## Stage 15 objective

Add deterministic evidence-based location suggestions without conflating them with known current location:

1. Keep `Item.current_location_id` as the sole authoritative current-location fact and add no persistent inferred-location state.
2. When current location is unknown, derive read-only candidates from the item's own location history and from current locations of related items sharing category/tags.
3. Rank suggestions deterministically and expose explicit evidence rather than fabricated confidence/probability.
4. Add a read-only agent tool requiring a resolved item; suggestions must not directly grant mutation authorization for returned locations.
5. Extend deterministic corpus/scenario coverage for last-known and related-item suggestions while preserving no-mutation guarantees.
6. Keep portable-v1, backup/restore, prompt versions, providers/models, embeddings, and deferred channels/features unchanged.

## Files to read first

1. `HANDOFF.md`
2. `AGENTS.md`
3. `README.md`
4. `src/ah_there_it_is/domain/search.py`
5. `src/ah_there_it_is/services/search.py`
6. `src/ah_there_it_is/services/inventory.py`
7. `src/ah_there_it_is/agent/tools.py`
8. `src/ah_there_it_is/eval_fixture.py`
9. `eval/corpus-v1.json`
10. `eval/scenarios-v1.json`
11. `src/ah_there_it_is/eval_checks.py`
12. `tests/test_search.py`
13. `tests/test_agent.py`
14. `tests/test_scenario_eval.py`
15. `Justfile`

## Orchestrated implementation workflow

Implementation-agent assignments and review records are archived under `agent-tasks/`. Current protocol v3 treats the trusted agent as both implementer and verifier.

For a normal implementation handoff, the agent fast-forwards `main`, implements only the assignment, self-reviews the complete diff, runs focused plus canonical local verification, opens the PR, waits for and diagnoses its own CI, applies task-related corrections, repeats until green, merges the PR, synchronizes local `main`, writes the compact review record required by the protocol, and returns only an aggregated summary. Raw test/Alembic/CI logs remain out of the orchestrator conversation unless needed to explain a blocker.

The orchestrator retains product/architecture direction, stage transitions, assignment formulation, and decisions where requirements conflict or a materially new design choice is needed. It does not repeat routine review/tests/CI already owned by the agent. The orchestrator guarantees that no concurrent repository work occurs between assignment publication and the agent's initial pull.

Assignment 0001 completed under v1. Assignment 0002/v2 was superseded before execution and is recorded in `agent-tasks/reviews/0002-r0.md`. Future implementation uses `agent-tasks/common/v3.md`; active Stage 15 work is `agent-tasks/assignments/0004-stage15-location-suggestions.md`.

## Development environment checkpoint

Internal ChatGPT sandbox baseline relevant to project/build compatibility: Python 3.13.5, pip 25.1.1, setuptools 82.0.1, wheel 0.46.3; the separate `build` package is not installed.

U24 project venv at `/home/gpt/projects/ah-there-it-is/.venv` is aligned for the same build path where practical: Python 3.12.3 (project-supported), pip 25.1.1, setuptools 82.0.1, wheel 0.46.3, no `build` package. `python -m pip wheel --no-build-isolation --no-deps .` was verified successfully there. Do not upgrade these merely because newer versions or deprecation notices exist; the active sandbox remains the primary compatibility reference.
