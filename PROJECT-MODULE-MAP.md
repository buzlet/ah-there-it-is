# Project module map

Current source baseline inspected: `main@25453f291a3c0a8d3a5c77a6ef8adfc533226c62`.

This file describes the current functional responsibility of project modules. It is a current map, not a historical stage log.

## Top-level files

### `pyproject.toml`
Python package metadata, Python >=3.12 requirement, runtime/test dependencies, package data, installed `ah-there-it-is` console entry point and pytest defaults.

### `Justfile`
Canonical repeated development/operator commands: tests, compilation, migrations, deterministic corpora/scenarios/retrieval evaluation, provider contract, server, backup/restore, portable import/export and bootstrap.

### `alembic.ini`
Source-development Alembic configuration pointing at the packaged migration environment.

### `.env.example`
Example application/provider environment configuration.

### `.github/workflows/ci.yml`
Single normal application PR CI: Python 3.12, compile/tests, migration/corpus/scenario/retrieval checks and CI-only coverage reporting.

### `.github/workflows/provider-contract.yml`
Separate provider/model adapter contract and manually invoked live provider/model probes.

### `.gitattributes`
Repository line-ending metadata needed by cross-platform development.

### `README.md`
Current user/developer overview, runtime/storage semantics and canonical commands.

### `AGENTS.md`
Current architecture invariants, development rules, process contract and decision boundary for implementation agents.

### `HANDOFF.md`
Compact current-state handoff between orchestration sessions.

---

# Python package: `src/ah_there_it_is`

## Application composition

### `app.py`
FastAPI application factory. Creates the application, database/session dependencies, routes and static/template wiring without doing startup migration.

### `config.py`
Application settings and environment resolution. Handles explicit database URL override, default database URL and provider/application settings.

### `data_paths.py`
Side-effect-free cross-platform user data paths. Resolves Unix/XDG, macOS and Windows `LOCALAPPDATA` defaults and the default `inventory.db`.

### `runtime_cli.py`
Installed `ah-there-it-is` command. Implements:
- `paths`;
- `doctor`;
- `repair-search-index`;
- `serve`;
- read-only schema-head gate before serving;
- loopback-only default and explicit `--allow-nonlocal` guard.

### `verification_paths.py`
Platform-neutral temporary paths/operations used by canonical development verification, especially migration checks.

### `__init__.py`
Package marker/version-level package surface.

---

# Persistence: `src/ah_there_it_is/db`

### `db/models.py`
SQLAlchemy persistence model.

Main tables/models:
- `Category`;
- `Location`;
- `Item`;
- `Alias`;
- `Tag`;
- `ItemTag`;
- `Event`;
- `Conversation`;
- `Message`;
- `AgentRunLog`;
- `ChatRequestRecord`;
- `AgentFeedback`;
- `ExperimentRun`;
- `ExperimentReview`.

This is the relational source of truth for inventory, history, conversations, idempotency and evaluation data.

### `db/session.py`
SQLAlchemy engine/session construction, SQLite connection policy and scoped session helper.

### `db/search_schema.py`
SQLite FTS5 schema management:
- install search schema/triggers;
- drop it;
- rebuild derived FTS index.

### `db/search_consistency.py`
Read-only comparison between authoritative Item/Alias/Tag data and derived FTS state. Used by doctor/import verification and FTS repair safety.

## Packaged migrations

### `db/migrations/__init__.py`
Programmatic packaged Alembic runner:
- construct migration config;
- discover heads;
- explicit upgrade/downgrade;
- schema check.

### `db/migrations/env.py`
Alembic runtime environment.

### `db/migrations/script.py.mako`
Migration revision template.

### Migration revisions

- `ae83dd1ff537_initial_domain_model.py` — initial Category/Location/Item/Event relational model.
- `c4cfe3a3e921_add_item_search_fts.py` — FTS5 derived item search schema/triggers.
- `7b1934a4d3b0_add_conversations.py` — persisted conversations/messages.
- `e74d21e14d57_add_agent_evaluation_logs.py` — agent evaluation/run logging.
- `cd2ab808e0c6_add_experiment_replay_tables.py` — prompt/model experiment and human-review storage.
- `f19b2c4d6e81_add_chat_request_idempotency.py` — durable request-key idempotency.
- `b62f9d8a3c41_add_item_tag_reverse_index.py` — reverse lookup index for ItemTag scale paths.
- `a31d7f4e9c20_add_chat_request_recovery_audit.py` — crash/recovery audit state for idempotent requests.
- `d24a8f1c3e90_add_agent_mutation_receipts.py` — persisted committed mutation receipts.
- `a4b7c9d2e610_add_location_truth.py` — Stage 26 `location_status`, terminal lifecycle and conservative backfill/invariants.

---

# Domain primitives: `src/ah_there_it_is/domain`

### `domain/names.py`
Shared normalization:
- `normalize_name`;
- `normalize_search_text`.

Used consistently by domain identity and deterministic search.

### `domain/states.py`
Controlled enums:
- `ItemState`;
- `LocationStatus` (`known`, `unknown`, `in_use`, `not_applicable`).

### `domain/search.py`
Typed deterministic search result objects such as `SearchCandidate` and `ItemSearchCandidate`.

### `domain/exceptions.py`
Domain validation/not-found/conflict exception types shared by service boundaries.

### `domain/__init__.py`
Domain package surface.

---

# Domain/read services: `src/ah_there_it_is/services`

### `services/inventory.py`
Central transactional domain service. This is the primary write boundary.

Major operations:
- Category create/update;
- Location create/update;
- Item create/update;
- move Item to known Location;
- `take_item`;
- mark location unknown;
- discard Item;
- mark sold;
- reactivate terminal Item;
- Item/Location/Category reads;
- bounded Item Event history;
- bounded direct Location contents.

Owns domain invariants, Event creation, historical location/category evidence and transaction-safe state transitions.

### `services/search.py`
Deterministic bounded retrieval:
- Items;
- Locations;
- Categories;
- Tags.

Combines exact/normalized identity, aliases, tags, attributes and bounded FTS candidates with stable ranking.

### `services/location_suggestions.py`
Read-only evidence-based location suggestions for Items whose location status is `unknown`.

Evidence includes own last-known history and related currently located Items. Suggestions do not authorize writes.

### `services/catalog.py`
Read projections for browser/catalog:
- paged Item catalog;
- browser search;
- Location/Category detail;
- tree paths;
- Item detail projection;
- lifecycle/location filters.

### `services/activity.py`
Bounded Event/Activity timeline projections and Event detail. Uses historical snapshot paths when available and avoids presenting current paths as historical truth.

### `services/conversations.py`
Persistent human-visible conversations/messages plus bounded prior-message retrieval specifically for agent context.

### `services/chat_requests.py`
Durable chat request idempotency and crash recovery.

Implements reservation/execution/replay/conflict/recovery semantics around a client request key.

### `services/evaluation.py`
Agent run logging and user feedback. Produces evaluation summaries and stable/sanitized model/provider config for later analysis.

### `services/experiments.py`
Persistence and summaries for controlled prompt/model replay experiments and human review.

### `services/__init__.py`
Service package marker/surface.

---

# Agent layer: `src/ah_there_it_is/agent`

## Provider-neutral protocol

### `agent/protocol.py`
Core provider-neutral types:
- `AgentMessage`;
- `ToolCall`;
- `ToolDefinition`;
- `LLMClientInfo`;
- `LLMResponse`;
- `LLMClient` protocol.

Application logic depends on these interfaces rather than a model vendor.

### `agent/runner.py`
Main bounded agent loop.

Responsibilities:
- builds system + bounded prior context + current user input;
- invokes `LLMClient`;
- executes tool rounds;
- enforces mutation-turn failure/rollback semantics;
- records exact run input/trace;
- commits successful conversation/run state;
- returns `AgentRunResult` with committed receipts.

### `agent/tools.py`
Tool registry/dispatcher over application services.

Responsibilities:
- determines available tool definitions;
- validates typed inputs;
- executes read/mutation tools;
- maintains current-run capability state;
- formats tool messages;
- prevents LLM from bypassing service boundaries.

### `agent/write_resolution.py`
Strong write-target authorization.

Resolves Items/Locations/Categories using database-wide exact identity evidence and performs revalidation for mutation safety. Search score/result position is not sufficient write authority.

### `agent/schemas.py`
Pydantic tool input contracts.

Includes search/read/create/update/move/take/unknown/terminal/reactivation inputs and the required/nullable distinctions needed by provider schemas.

### `agent/receipts.py`
Compact backend-owned mutation receipts. They report committed operation/entity/id/change/event/before-after evidence independently of assistant text.

### `agent/errors.py`
Agent/tool/provider error taxonomy: tool execution/precondition, loop limit, failed turn and provider protocol/request errors.

## LLM implementations/adapters

### `agent/factory.py`
Builds the configured LLM client/provider from application settings.

### `agent/openai_compatible.py`
Synchronous OpenAI-compatible chat-completions adapter with tool calling.

### `agent/gemini.py`
Native Gemini `generateContent` adapter, including function-call state/opaque provider state preservation across rounds.

### `agent/heuristic.py`
Very small offline rule-based development/smoke client. Not product intelligence.

### `agent/fakes.py`
Offline scripted LLM test doubles.

### `agent/scenario_mock.py`
Deterministic scenario-driven LLM double.

Loads versioned scenario suites and emits predefined tool calls/final responses while validating expected tool results. This is the main model-independent application behavior harness.

### `agent/metadata.py`
Safe provider trace metadata, especially base URL sanitization and removal of credentials/query/fragment leakage.

## Evaluation/replay support

### `agent/experiments.py`
Captured-evidence prompt/model replay engine. Replays model choices against previously captured tool evidence without mutating a live inventory.

### `agent/__init__.py`
Agent package marker/surface.

---

# Storage and onboarding

### `storage.py`
Large storage/recovery boundary.

Implements:
- SQLite file validation/integrity checks;
- WAL-safe backup;
- restore with safety backup;
- isolated restore rehearsal;
- portable inventory parser/validator;
- frozen `inventory-portable-v1`;
- current `inventory-portable-v2`;
- portable export/import;
- schema revision checks;
- preservation of stable IDs/timestamps/history;
- FTS reconstruction/validation after portable import.

### `storage_cli.py`
Operator CLI for storage tasks:
- explicit schema upgrade/check;
- backup/validate/restore/rehearsal;
- portable export/import/dry-run;
- bootstrap validation/apply.

### `bootstrap.py`
Strict `inventory-bootstrap-v1` onboarding import for an empty current-schema database.

Bootstrap supplies semantic inventory content but not stable IDs/history/timestamps; current services generate those.

### `database_doctor.py`
Provider-independent active-database diagnostics.

Checks SQLite integrity, foreign keys, schema/head, domain invariants, normalized identities and FTS consistency. The only explicit repair is derived search-index rebuild.

---

# Web layer: `src/ah_there_it_is/web`

### `web/dependencies.py`
FastAPI session dependency wiring.

### `web/routes.py`
HTTP/HTML endpoint definitions for:
- chat;
- request recovery/audit;
- Items/catalog/search;
- Item create/edit/location/lifecycle actions;
- Locations/Categories;
- Activity/Event history;
- evaluations/feedback;
- experiments/reviews.

Routes delegate business logic to services rather than implementing persistence rules.

### `web/schemas.py`
HTTP Pydantic request/response contracts for chat, Item/tree administration, recovery, feedback, conversations and experiments.

## Templates

- `templates/base.html` — shared page shell/navigation.
- `templates/index.html` — main chat/index page.
- `templates/items.html` — paged/searchable Item catalog with lifecycle/location status.
- `templates/item_detail.html` — Item detail, history, suggestions and explicit location/lifecycle actions.
- `templates/item_new.html` — new Item form.
- `templates/_item_form.html` — shared Item form partial.
- `templates/locations.html` — Location tree/list surface.
- `templates/categories.html` — Category tree/list surface.
- `templates/tree_detail.html` — Location/Category node detail and direct contents.
- `templates/tree_edit.html` — tree create/edit/reparent UI.
- `templates/activity.html` — paged Activity/Event timeline.
- `templates/activity_detail.html` — Event details and historical path evidence.
- `templates/chat_requests.html` — idempotent request/recovery diagnostic UI.
- `templates/evaluations.html` / `evaluation_detail.html` — agent run/evaluation inspection.
- `templates/experiments.html` / `experiment_detail.html` — prompt/model experiment history and review.

## Static assets

- `static/chat.js` — chat submission/response UI.
- `static/chat_requests.js` — request id/retry/recovery browser logic.
- `static/item.js` — explicit Item move/take/unknown/sold/discard/reactivation form behavior.
- `static/tree.js` — Category/Location tree administration interactions.
- `static/experiment.js` — experiment/review UI behavior.
- `static/style.css` — application styling.

---

# Deterministic evaluation and model research

### `eval_corpus.py`
Typed schema/loader for versioned evaluation cases and persisted-state expectations.

### `eval_checks.py`
Shared deterministic postcondition evaluator for inventory/database assertions.

### `eval_fixture.py`
Creates a fixed synthetic inventory fixture so live/model comparisons do not depend on user production data.

### `scenario_eval.py`
Runs the deterministic application scenario suite with `ScenarioLLMClient` and validates persisted postconditions.

### `retrieval_eval.py`
Offline retrieval benchmark for current SearchService semantics.

Reports per-case/language results and the bounded candidate-starvation diagnostic.

### `model_probe.py`
Tests provider/model tool-calling protocol without inventory business logic. Covers tool selection, multi-tool calls, result continuation and final text.

### `provider_smoke.py`
Minimal configured live-provider connectivity smoke test.

### `live_eval.py`
Runs the versioned corpus against a real configured provider using a fresh deterministic inventory fixture per case.

### `live_compare.py`
Compares two live-evaluation reports descriptively without declaring a model winner.

### `evaluation_export.py`
Exports rated historical agent runs to JSON for research/replay.

### `experiment_replay.py`
CLI for replaying captured rated runs against a prompt/model variant.

---

# Evaluation data: `eval/`

### `eval/corpus-v1.json`
Versioned application evaluation cases and expected persisted-state behavior.

### `eval/scenarios-v1.json`
Deterministic multi-step scenario scripts for the mock LLM/application pipeline.

### `eval/retrieval-robustness-v1.json`
RU/UK/EN deterministic retrieval corpus, ambiguity/no-match cases and candidate-starvation diagnostic.

### `eval/retrieval-robustness-v1.md`
Human-readable interpretation/baseline notes for retrieval measurements.

### `eval/model-probes-v1.json`
Provider-neutral model/tool protocol probe cases.

### `eval/results/2026-09-22-groq-v1-v2-representative.md`
Historical representative live evaluation result retained for comparison/research.

---

# Tests: `tests/`

## Shared support

### `tests/conftest.py`
Common pytest fixtures and database/application setup.

### `tests/scale_fixture.py`
Deterministic target-scale fixture with roughly 1000 Items and nested Locations/Categories for structural performance/query-bound tests.

### `tests/fixtures/inventory-portable-v1.json`
Frozen historical portable-v1 compatibility fixture.

### `tests/fixtures/inventory-bootstrap-v1.json`
Bootstrap onboarding fixture.

## Domain/services

- `test_domain.py` — core InventoryService/domain invariants and state transitions.
- `test_search.py` — deterministic ranking/candidate behavior.
- `test_location_suggestions.py` — suggestion evidence/ranking/status eligibility.
- `test_bounded_reads.py` — bounded history/Location reads and pagination.
- `test_activity.py` — Activity/Event projections and historical paths.
- `test_target_scale.py` — bounded structural/query behavior at target scale.
- `test_write_target_safety.py` — strong mutation-target resolution/revalidation.
- `test_conversation_context.py` — bounded agent prior-message context.

## Agent/application transaction safety

- `test_agent.py` — agent loop/tool integration and model-independent behavior.
- `test_atomic_turn_receipts.py` — transactional mutation-turn rollback and committed receipts.
- `test_idempotency.py` — request-key replay/conflict behavior.
- `test_idempotency_crash.py` — faults around commit, uncertain response and durable recovery.
- `test_provider.py` — adapter/provider schema and protocol contracts.
- `test_trace_config_privacy.py` — provider metadata secret sanitization.
- `test_prompts.py` — prompt/template contract assertions.
- `test_model_probe.py` — provider-neutral model-probe engine.

## Web/UI

- `test_app.py` — FastAPI/chat/API behavior.
- `test_manual_admin.py` — browser/manual create/edit/tree/Item operations.
- `test_browser_discovery.py` — browser search/detail navigation.
- `test_runtime_cli.py` — installed runtime commands/schema/serve guard.
- `test_data_paths.py` — stable cross-platform data-home behavior.

## Storage/migrations

- `test_migrations.py` — migration chain/schema behavior.
- `test_storage.py` — backup/restore/portable storage operations.
- `test_restore_rehearsal.py` — isolated rehearsal safety.
- `test_portable_compatibility.py` — frozen v1 -> current import compatibility.
- `test_bootstrap.py` — bootstrap validation/preflight/apply/rollback.
- `test_database_doctor.py` — diagnostics and derived FTS repair.
- `test_wheel_migrations.py` — real wheel build/install from outside checkout, packaged migrations/templates/static/runtime/backup behavior.

## Evaluation

- `test_eval_checks.py` — shared persisted-state checks.
- `test_evaluation.py` — run logs/feedback/evaluation projections.
- `test_experiments.py` — experiment persistence/replay/review.
- `test_scenario_eval.py` — deterministic scenario evaluator.
- `test_retrieval_eval.py` — retrieval corpus/evaluator/gating diagnostics.
- `test_live_eval.py` — live-evaluation harness behavior using doubles.
- `test_live_compare.py` — report comparison semantics.

---

# Process documentation

The active documentation policy is being compacted on branch `process/docs-archive-direct-shell-v7`.

Current intended active files:

- `README.md` — product/operator overview;
- `AGENTS.md` — current architecture/process invariants;
- `HANDOFF.md` — compact current-state handoff;
- `PROJECT-MODULE-MAP.md` — this module map;
- `agent-tasks/common/v7.md` — current implementation protocol;
- `agent-tasks/designs/future-decision-gates.md` — unresolved product decisions.

Completed assignments/reviews/protocol generations are historical evidence and are being moved under `agent-tasks/archive/` so normal implementation agents do not read them by default.
