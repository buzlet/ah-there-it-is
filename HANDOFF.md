# Session handoff

## Authoritative repository state

- Repository: `buzlet/ah-there-it-is`
- Default branch: `main`
- Always verify current `origin/main`, PR state, and CI before starting new work.
- This handoff supersedes the pre-Stage-12 handoff that existed at commit `198061c9c88353a950cb90f2ec8fcd6cabd51edf`.
- **Stages 0–22 are complete.**
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

## Stage 17 delivered

- installed `ah-there-it-is serve` console command with local-only defaults and explicit host/port override;
- exact-head read-only SQLite runtime gate before Uvicorn, rejecting missing/uninitialized/behind/ahead/incompatible schema without creation or migration;
- side-effect-light `ah_there_it_is.app` import with `create_app()` as the real factory;
- development `just serve` separated as factory + reload behavior;
- real wheel smoke exercises installed console metadata and localhost health/index/static serving outside checkout;
- explicit migration/bootstrap/recovery lifecycle preserved;
- complete protocol-v3 verification green: 210 tests, 42/42 scenarios, provider contract, Python 3.12/3.13 CI.

## Stage 18 delivered

- stdlib-only stable per-user data-home resolver for Unix/XDG, macOS, and Windows;
- CWD-independent default `<data-home>/inventory.db` with explicit database URL precedence;
- home-anchored relative path handling and blank-override policy;
- side-effect-free settings/import/create-app/runtime-schema/paths resolution;
- only explicit storage upgrade may create the missing SQLite parent/database;
- read-only installed `paths` JSON surface without credential leakage;
- real wheel cross-CWD upgrade/serve proof with no stray working-directory DB/WAL/SHM files;
- complete protocol-v3 verification green: 225 tests, 42/42 scenarios, provider contract, Python 3.12/3.13 CI.

## Stage 19 delivered

- deterministic test-only target-scale generator with exactly 1000 items, 200 nested locations, 31-category tree, rich search/suggestion targets, and ambiguity cases;
- bounded SQL/FTS-first item candidate discovery with existing deterministic ranking preserved;
- relevant-row-only location-suggestion evidence queries;
- `ix_item_tags_tag_id` reverse lookup index and migration revision `b62f9d8a3c41`;
- paged `/items` catalog with 50 default / 100 maximum and deterministic navigation/order;
- grouped bounded-query location/category direct-item counts;
- structural ORM/query-count scale regressions instead of timing gates;
- complete protocol-v3 verification green: 230 tests, 42/42 scenarios, provider contract, Python 3.12/3.13 CI.

## Stage 20 delivered

- typed read-only doctor for SQLite integrity/FK/exact schema plus normalized identities, hierarchy, state/quantity, names, and FTS schema/content;
- machine-readable installed `doctor` with stable exit status and no database/filesystem side effects;
- intentional duplicate Item identity warnings remain non-fatal;
- reusable bounded FTS consistency boundary shared by portable import and doctor;
- explicit idempotent `repair-search-index` limited to derived FTS objects/content after authoritative/base checks pass;
- repair preserves every non-FTS application table and refuses base-data corruption;
- WAL/read-only, corruption, 1000-item, portable-import, repair and installed-wheel coverage;
- complete protocol-v3 verification green: 247 tests, 42/42 scenarios, provider contract, migration checks, Python 3.12/3.13 CI.

## Stage 21 delivered

- safe service-layer Category/Location rename, description and reparenting with stable IDs and cycle/duplicate prevention;
- manual browser/API creation of Items, Categories and Locations;
- full Item correction for aliases, tags, attributes, category, location, description, state, quantity and name;
- full-path tree parent selection with browser and service-level cycle protection;
- atomic manual Item field/location edits with normal provenance/history/FTS behavior;
- packaged templates/static assets and target-scale pagination non-regression;
- complete protocol-v3 verification green: 254 tests, 42/42 scenarios, provider contract, migration checks, Python 3.12/3.13 CI.

## Stage 22 delivered

- Bounded browser Item search through the existing deterministic SearchService, with blank-query catalog pagination preserved.
- Read-only Location/Category detail navigation with full paths, parent/children, and paged direct Items.
- Stable-ID links connect search results, Item pages, and tree pages.
- Target-scale browser reads, installed-wheel assets, and 42 deterministic scenarios verified without changing schema, ranking, or mutation behavior.

## Orchestrated implementation workflow

Implementation-agent assignments and review records are archived under `agent-tasks/`. Assignment 0010 is the final assignment issued under protocol v3. After this process change is merged, future assignments use `agent-tasks/common/v4.md`.

Protocol v4 uses a stage-owned seeded branch rather than a separate orchestrator documentation PR. After accepting the previous agent's compact report, the orchestrator does not re-run routine tests, re-review the successful implementation diff, or monitor that implementation CI. It reads the prior review/current strategy plus only the source areas needed to choose the next product or architecture gap.

For the next stage the orchestrator synchronizes `main`, creates the assignment-named feature branch from it, writes exactly one immutable seed commit containing the new assignment and required strategy/status documentation, performs only lightweight structural/document consistency checks, and pushes the branch. It opens no PR and waits for no application CI. The pushed seed branch is then handed to the implementation+verification agent.

The agent fetches and continues that exact branch; it does not create a replacement branch, amend/rebase/squash the seed, or force-push rewritten history. The agent implements the assignment in later commits, self-reviews, runs focused plus canonical verification, writes the review record, updates the assigned stage to factually complete without choosing the next stage, opens the single implementation PR, owns its CI/fix loop, and merges with a merge commit so the seed remains in repository history. After merge it synchronizes clean local `main` and returns only the compact v4 report.

Normal GitHub workflows run full application/provider-contract checks only for pull requests that change executable/test/schema/packaging/workflow content. Ordinary feature-branch pushes do not run CI, so orchestrator seed pushes are free of CI. Pull requests changing only the recognized strategy/process documentation (`AGENTS.md`, `HANDOFF.md`, `README.md`, `agent-tasks/**`) are ignored by those heavy workflows entirely. This keeps one normal full PR-CI cycle per implemented stage without weakening implementation verification. The repository currently has no required-status-check branch protection; if such protection is introduced later, reconcile it with docs-only path filtering so skipped workflows cannot become permanently required.

The orchestrator guarantees no concurrent repository work between seed publication and the agent's initial pull. Ordinary implementation/test failures remain the agent's responsibility; only genuine architecture/product/infrastructure blockers return to the orchestrator.

Assignment 0001 completed under v1. Assignment 0002/v2 was superseded before execution and is recorded in `agent-tasks/reviews/0002-r0.md`. Assignments 0003–0010 use the historical protocol recorded by each assignment; future assignments issued after this process transition use v4.

## Development environment checkpoint

Internal ChatGPT sandbox baseline relevant to project/build compatibility: Python 3.13.5, pip 25.1.1, setuptools 82.0.1, wheel 0.46.3; the separate `build` package is not installed.

U24 project venv at `/home/gpt/projects/ah-there-it-is/.venv` is aligned for the same build path where practical: Python 3.12.3 (project-supported), pip 25.1.1, setuptools 82.0.1, wheel 0.46.3, no `build` package. `python -m pip wheel --no-build-isolation --no-deps .` was verified successfully there. Do not upgrade these merely because newer versions or deprecation notices exist; the active sandbox remains the primary compatibility reference.
