# AGENTS.md

## Product

- Product name: **Ah, There It Is!**
- Repository: `ah-there-it-is`
- Python package: `ah_there_it_is`
- Goal: a local-first personal inventory memory controlled primarily through natural-language text.

## Architecture invariants

1. The LLM never accesses or writes the database directly.
2. Existing entities are referenced by stable IDs in mutation operations.
3. An LLM may search and inspect candidates before choosing an entity.
4. Creating a new item, location, or category is an explicit operation; mutation tools must not silently create named entities.
5. Domain/service code owns validation, deduplication rules, identity, and transaction boundaries.
6. Every material item mutation produces a history event. Natural-language source text is retained on events when available.
7. HTTP handlers and LLM tool handlers stay thin and call the same service layer.
8. Known locations and inferred/probable locations are different concepts and must never be silently conflated.
9. Existing entities are never resolved by a mutation tool from arbitrary free-text names; resolution/search happens before mutation.
10. Prefer the simplest implementation that preserves these invariants. Avoid framework layers without a concrete need.

## MVP constraints

- Text only. No voice, Telegram, images, QR codes, PWA/offline behavior, or MCP in the initial MVP.
- SQLite is the initial database.
- Synchronous SQLAlchemy is preferred until concurrency creates an actual need for async database access.
- Search begins with exact/normalized matching and SQLite FTS5. Embeddings are deferred until real queries justify them.
- Keep the LLM provider behind a small application interface so providers/models can be replaced.
- Do not introduce LangChain, LangGraph, Hermes, or another agent framework for the initial tool loop unless the native implementation becomes materially complex.

## Development rules

- Work in focused feature branches and merge only after tests pass.
- Add tests with each behavior change.
- At the end of every stage, update this file with a concise completed-stage summary and the concrete next-stage plan before merging.
- Do not add dependencies that cannot be exercised in the active development environment.
- Keep module imports side-effect-light; application creation belongs in `create_app()`.
- Preserve local-first operation. External LLM APIs may be adapters, never storage authorities.
- **Application development and application CI must never depend on a real LLM/provider.** Use deterministic scenario mocks for application behavior; test provider/model compatibility in the separate contract pipeline.
- Every application scenario must have at least one independent postcondition against persisted application state. Scenario completion alone is not success; `scenario-eval` must fail on failed checks or unchecked cases. The current v1 corpus/scenario suite has 40/40 automatic postconditions.
- Google/Gemma provider probes are contract-only and must remain outside application CI. The current hosted probe uses `gemma-4-31b-it`, optional `thinkingConfig=HIGH`, and a 3.2-second minimum gap between every model request to stay below a 20 RPM target.
- Use **Just** (`Justfile`) as the canonical runner for repeated development operations such as tests, checks, migrations, and the development server. Do not duplicate recurring command sequences in documentation or ad-hoc scripts when a Just recipe is appropriate.
- If `just` itself is unavailable in a constrained environment, keep the `Justfile` authoritative and run the exact underlying recipe commands directly until `just` is available; do not add a network dependency merely to bootstrap the task runner.
- Development tool/dependency/workflow versions are chosen primarily for compatibility with versions available and exercisable in the active development sandbox. Do not upgrade dependencies, GitHub Actions, or runtimes merely to silence upstream deprecation warnings; change them when the active environment or required functionality makes the change necessary, or when a task explicitly requests it.
- When work is delegated through the orchestrated implementation workflow, follow the versioned protocol and assignment archive under `agent-tasks/`. Current protocol v4 uses one orchestrator-seeded stage branch: the orchestrator creates one immutable assignment/strategy seed commit from synchronized `main` and pushes it without opening a PR; the trusted implementation+verification agent continues that exact branch through implementation, self-review, canonical checks, one implementation PR/CI correction loop, merge, main synchronization, stage-completion documentation, and compact reporting. The seed commit and issued assignment are never amended, rebased away, squashed, or rewritten. The orchestrator retains product/architecture direction, next-stage selection, assignment design, and decisions on genuine blockers; after a successful agent report it does not repeat routine diff review, tests, or CI verification and reads only the prior review/current strategy plus files needed to choose the next gap.

## Stage status

### Stage 0 — complete

- Python/FastAPI project skeleton, configuration, `/health`, and minimal web shell.
- Sandbox-compatible dependency set verified without Internet access.
- Offline direct execution and editable installation verified.

### Stage 1 — complete

- SQLite persistence layer with synchronous SQLAlchemy 2 engine/session policy.
- SQLite foreign keys, busy timeout, and WAL policy enabled where supported.
- Alembic migration environment and initial schema migration.
- Domain entities: `Item`, `Location`, `Category`, `Alias`, `Tag`, `ItemTag`, `Event`.
- Arbitrarily nested location/category trees using `parent_id`.
- Structured item attributes stored as JSON while preserving human-readable descriptions.
- Controlled item-state vocabulary.
- `InventoryService` operations for category/location/item creation, item update/move/take, location contents, and item history.
- Explicit duplicate protection for tree nodes and item creation, with an explicit override for legitimate identical items.
- Material item creation/update/movement records immutable history events, including original natural-language text when supplied.
- Domain behavior covered by isolated SQLite tests.
- `Justfile` introduced as the canonical interface for repeated developer operations.

### Stage 2 — complete

- Deterministic candidate retrieval added before any LLM reasoning.
- Separate retrieval normalization handles punctuation/separator variants without changing Stage 1 identity/deduplication rules.
- Typed Pydantic candidate DTOs return stable entity IDs, match type, deterministic score, and relevant context.
- Item ranking is explicit: exact name > exact alias > exact structured attribute > retrieval-normalized name/alias > exact tag > substring > FTS5.
- Location/category search returns full ancestry paths so duplicate leaf names remain distinguishable.
- SQLite FTS5 indexes item name, aliases, description, tags, and structured attributes.
- FTS5 content is maintained automatically by SQLite triggers across item, alias, and tag mutations.
- Stage 2 migration backfills FTS data for an already-populated Stage 1 database.
- Alembic autogenerate explicitly ignores FTS5 virtual/shadow tables because they are owned by hand-written migrations.
- FTS5 is a schema requirement; missing migrations must fail visibly rather than silently degrade retrieval.
- Ambiguity, duplicate names, path disambiguation, punctuation safety, ranking, trigger synchronization, and migration backfill are covered by tests.
- Embeddings remain intentionally deferred; no measured Stage 2 case requires them yet.

### Stage 3 — complete

- Provider-neutral `LLMClient`, message, tool-call, response, and JSON-schema contracts added without an agent framework.
- Typed Pydantic tool inputs expose deterministic search/read operations and explicit stable-ID mutations.
- `ToolDispatcher` is the only LLM-facing mutation boundary; it never exposes SQL or a database session.
- Bounded `AgentRunner` enforces a hard `max_rounds` limit and returns malformed/unknown tool calls as structured tool errors.
- Tool authorization distinguishes **seen** candidates from **resolved** candidates: ambiguous/tied results may be inspected but cannot be mutated.
- Deterministic Stage 2 score gaps can resolve a clear top candidate; tied/close candidates remain mutation-ineligible until search is refined or the user clarifies.
- Tool capabilities are frozen per LLM round, so a search and dependent mutation emitted in the same model response cannot cheat by consuming results the model has not seen yet.
- `create_*` operations require a prior same-name search; existing category/location/item targets must be resolved before mutation.
- Minimal `Conversation`/`Message` persistence stores only human-visible user/final-assistant turns needed for clarification across requests; tool traces are not mixed into conversation history. Stage 4 stores them separately as evaluation/run logs.
- `ScriptedLLMClient` provides deterministic complete offline agent tests.
- `HeuristicLLMClient` provides a deliberately tiny offline smoke adapter for `Где X?` and `Положил/переложил X в Y`; it is development scaffolding, not a production NLP model.
- No real model-provider adapter was added because the active sandbox cannot exercise an external API. The provider boundary is ready for one later.
- `Justfile` now includes dedicated `test-agent` and `migration-check` recipes in addition to the canonical test/check/migrate/server commands.

### Stage 4 — complete

- First usable text-only web application added with FastAPI/Jinja2/vanilla JavaScript; no frontend framework or network-served assets are required.
- `POST /api/chat` accepts a message plus optional stable `conversation_id`, invokes the existing bounded `AgentRunner`, and returns `conversation_id`, `run_id`, response text, and round count.
- Browser chat persists the active conversation in local storage and restores persisted human-visible turns through `GET /api/conversations/{id}`.
- `HeuristicLLMClient` remains the explicit offline development provider; provider construction is isolated behind the application factory.
- Read-oriented web pages added for items, nested locations, nested categories, item detail, and item history.
- Minimal manual item correction is service-backed through `PATCH /api/items/{id}` and records normal domain history events rather than bypassing validation.
- Evaluation logging is first-class: each agent run stores exact system prompt, prompt version, SHA-256 prompt hash, provider/model/config metadata, input message snapshot, per-round tool calls/results, final result or failure, and round count.
- User feedback is attached to a concrete agent run as a 1–5 rating plus optional comment and can be updated later.
- `/evaluations` groups results by exact `(prompt_version, prompt_hash, provider, model)` and shows run/rating counts plus average rating; `/evaluations/{run_id}` exposes the full captured trace for inspection.
- Alternate system prompts can be supplied by file (`AH_THERE_IT_IS_PROMPT_FILE`) while `AH_THERE_IT_IS_PROMPT_VERSION` gives the human-readable experiment label; hash protects against forgotten version bumps.
- Rated runs can be exported as JSON with `just eval-export`, preserving the material needed for later prompt/model experiments.
- Failed agent executions are logged as evaluation runs too, so failure-prone variants are not silently excluded from comparison.
- A real Uvicorn smoke flow was exercised offline: chat mutation -> persisted item -> 1–5 feedback -> conversation restore -> evaluation summary -> rated-run export.
- `Justfile` remains canonical and now includes `test-web` and `eval-export`.

### Stage 5 — complete

- Added a replaceable synchronous OpenAI-compatible Chat Completions adapter using only the Python standard library; no provider SDK or agent framework was introduced.
- Provider configuration is explicit: endpoint, provider label, model, timeout, temperature, and provider-specific extra request fields. API keys are never written to evaluation metadata.
- Provider responses now preserve non-sensitive response metadata such as response ID, finish reason, and usage in the per-round run trace.
- The adapter serializes existing typed tool definitions to OpenAI-compatible function tools and parses/validates returned JSON tool arguments before the normal backend dispatcher sees them.
- Local HTTP contract tests exercise request/response/tool-call behavior without Internet access. The live external endpoint itself is not claimed as tested from the network-isolated sandbox.
- Added `ExperimentRun` and `ExperimentReview` persistence plus an Alembic migration. Experiment runs are separate from live `AgentRunLog` history and never overwrite source runs.
- Added conservative controlled replay: a variant receives the original input context with a replacement system prompt and may consume only captured source tool results in their exact original order. Different/extra tool requests are marked `diverged`; replay never executes live inventory mutations.
- Added experiment aggregate metrics: completed/diverged/failed counts, average rounds, source/variant human ratings, pairwise baseline/variant/tie/both-bad review counts, a clearly-labelled clarification heuristic, general tool-error rate, and mutation-error rate.
- Added `/experiments` and `/experiments/{id}` side-by-side review UI plus API persistence for pairwise choice, optional 1–5 variant rating, and comments.
- Added versioned prompt files under `prompts/`; a test guarantees `inventory-v1.txt` remains byte-for-byte equal to the built-in default prompt. `inventory-v2-strict.txt` is the first reviewable variant.
- Added `experiment-replay` CLI/Just recipe for rated historical runs and `provider-smoke` for a real configured endpoint.
- Added GitHub Actions CI on Ubuntu 24.04 / Python 3.12 and 3.13 using the canonical `just` commands, plus a manual live-provider smoke job gated by repository variables/secrets.
- Stage 5 application/package version is `0.2.0`.

### Stage 6 — complete

Stage 6 was deliberately restructured after live-provider work began coupling application progress to model quirks and quotas.

#### Application pipeline

- Added `ScenarioLLMClient`, a deterministic declarative `LLMClient` test double. It supplies the model-side decisions while the real `AgentRunner`, dynamic capability gating, `ToolDispatcher`, search/services, SQLite fixture, mutations, history, and conversation persistence continue to execute normally.
- Scenario arguments resolve IDs from actual prior tool results with references such as `${tool:search_items:result.0.id}`; hard-coded fixture entity IDs are not used to bypass retrieval.
- Scenario steps can require offered tools, forbid unsafe capabilities, assert successful prior tool results, and check result cardinality/value before proceeding. Divergence raises `ScenarioMismatchError`.
- Failed scenarios preserve partial agent/tool traces for deterministic diagnosis.
- `eval/scenarios-v1.json` now has a scenario for every one of the 40 cases in `eval/corpus-v1.json`; tests require the two ID sets to remain exactly equal.
- `scenario_eval` creates a fresh `inventory-fixture-v1` SQLite database per case and evaluates normal corpus postconditions. It requires no network, provider key, model, temperature, or quota.
- Multi-turn clarification, create/update/move/take, ambiguity, nested locations, history, language normalization, descriptive retrieval, duplicate prevention, and safety cases are all executable application scenarios.
- The scenario suite exposed two real deterministic retrieval defects:
  1. tree ancestry queries could tie an intended node with descendants; a new `exact_path` rank resolves the exact normalized path while preserving ambiguity for duplicate leaf names;
  2. two-token OR-FTS searches could accept one-token noise, blocking legitimate creates; multi-token FTS now requires at least two overlapping query tokens.
- Existing duplicate-information update cases were made explicitly idempotent: when the fixture already contains the stated fact, the expected application behavior is no redundant mutation/event.

#### Provider/model pipeline

- Added `model_probe`, which exercises only `LLMClient.complete(messages, tools)` with static protocol cases. It does not create an inventory database, invoke `ToolDispatcher`, or execute application mutations.
- `eval/model-probes-v1.json` now covers the complete provider-neutral protocol surface currently required by the application: single tool selection with JSON arguments, multiple independent tool calls in one response, single-tool result continuation, parallel-tool result continuation, and final plain text. Multi-round probes preserve returned `ToolCall` objects in memory, including provider-only opaque state, while synthetic tool results keep the probe independent from inventory business logic.
- `provider-contract` runs adapter/model-contract unit tests independently from application tests.
- `.github/workflows/ci.yml` is now `application-ci`: Python 3.12/3.13 checks plus the complete scenario suite, with no provider secrets or live-model jobs.
- `.github/workflows/provider-contract.yml` is separate: local adapter-contract tests run on push/PR; real Groq/Gemini probes are manual-only through the protected `live-llm-test` environment.
- Native Gemini and OpenAI-compatible adapters remain replaceable `LLMClient` implementations. Provider-specific protocol details, retries, quotas, thought signatures, or model tool-calling behavior must be handled and tested in this adapter pipeline, not encoded into application behavior.
- Historical `live_eval`, prompt replay, and `live_compare` remain available for deliberate end-to-end research. They are not application-development gates and must not be used to justify provider-specific application hacks.

#### Stage 6 evidence

- The earlier live-provider work remains useful evidence that both Gemini native function calling and Groq/OpenAI-compatible tool calling can drive complete agent loops, and the archived prompt comparison remains available under `eval/results/`.
- That evidence is intentionally decoupled from application correctness. A provider outage, quota exhaustion, invalid generated tool name, or stochastic answer must not turn application CI red.
- Current stable target: all 40 corpus scenarios pass deterministically through the real application stack with `ScenarioLLMClient`; provider-contract tests pass separately with real provider jobs skipped unless manually requested.

### Stage 7 — complete

- Extended the provider-neutral corpus postcondition vocabulary with exact item attributes, explicit category absence, global event-count deltas, and typed item-event assertions including optional source/destination location constraints.
- Kept the existing location, null-location, state, quantity, description, history-count, existence, and no-mutation checks; all checks operate on persisted application state after the scenario finishes.
- Mutation scenarios now verify effects independently from the scripted tool sequence. Every move checks final location plus exactly one expected movement/take event; every create checks the created item state/location/category policy plus exactly one creation event; material updates check state/quantity/description plus their update event.
- Read-only, ambiguity, safety, and idempotent-update cases retain explicit no-mutation checks so a scenario cannot pass merely because the mock produced a plausible final sentence.
- History scenarios now assert actual persisted event evidence rather than relying only on a successful history-tool call.
- `eval/corpus-v1.json` still contains the same 40 provider-independent cases and remains ID-aligned with `eval/scenarios-v1.json`.
- Added focused unit coverage for the shared postcondition evaluator.
- Final Stage 7 application CI is green on Python 3.12 and 3.13, and the complete 40-case scenario suite passes all independent postconditions. Provider-contract CI is separately green; real Groq/Gemini jobs remain manual-only and were not used to establish application correctness.

### Stage 8 — complete

- `AgentRunner` now owns the business transaction for one user turn. Its `ToolDispatcher` uses `InventoryService(autocommit=False)`, so successful mutation tools flush changes for subsequent tools but cannot commit independently.
- Standalone/manual `InventoryService` callers retain the historical `autocommit=True` behavior, so the transaction change is scoped to agent turns instead of silently changing every service consumer.
- On a successful final response, pending inventory mutations/history, the assistant conversation message, and the completed `AgentRunLog` are committed together.
- On any exception, `AgentRunner` first rolls back the turn transaction and only then records the failed run in a separate transaction. A failure log therefore cannot accidentally commit the business mutation it is describing.
- Conversation audit semantics are explicit: the user's message is persisted before tool execution and remains visible after a failed turn; no assistant message is persisted for that failed turn.
- Regression tests cover rollback after successful `move_item`, `create_item`, and `update_item` tool executions followed by `AgentLoopLimitError`. All assert both application state and history-event count return to their pre-turn values while the failed run trace is retained.
- A dedicated `ScenarioLLMClient` failure test performs real search -> move, deliberately omits the final mock step, receives `ScenarioMismatchError`, and proves the successful tool mutation is rolled back. Stage 8 therefore remains fully provider-independent.
- The unchanged 40-case application scenario suite remains green with strict Stage 7 state/event postconditions, proving successful agent turns still commit exactly the expected effects.
- Final Stage 8 application CI is green on Python 3.12 and 3.13. Provider-contract CI remains separate; real model jobs are manual-only and irrelevant to the atomicity guarantee.

### Stage 9 — complete

- Added optional client-supplied `request_key` to `POST /api/chat`. Existing clients may omit it; retry-safe clients should reuse the same key for the same logical submission.
- Added local SQLite `chat_requests` persistence with a unique request key, original requested conversation ID, normalized message payload, terminal status, linked completed `AgentRunLog`, error text, and timestamps. No Redis/network service is required.
- `ChatRequestService` reserves the unique key **before** creating an LLM/provider client or entering the agent loop. Only the request that wins the reservation may execute the callback.
- A completed duplicate with the exact same key/message/requested conversation returns the persisted `AgentRunResult`; it does not construct an LLM, execute tools, add conversation messages, or create more history events.
- Reusing a key with different content is an explicit conflict. A still-`processing` key returns 425 and does not execute a second loop. A previously failed key is not restarted implicitly; callers must use a new key for an intentional new attempt.
- `processing` records deliberately have no automatic TTL/restart policy. After an unknown process/network failure, preserving the block is safer than guessing that an earlier mutation did not commit.
- The idempotency reservation is committed separately before `AgentRunner`. On callback failure the service rolls back any open transaction before marking the reservation failed. Stage 8 turn atomicity therefore remains intact.
- Deterministic tests cover create, move, and update retries with exact event-count assertions; every retry returns the same run and produces no duplicate mutation/history. A separate test closes the first SQLAlchemy session and proves replay is reconstructed from persisted SQLite state rather than an identity-map artifact.
- API tests prove the cached path invokes `llm_factory` only once, conflicting keys return 409, and a `processing` key returns 425 without even constructing an LLM.
- Browser chat generates a stable UUID-like key per submission, persists the pending request in `localStorage`, and reuses it after reload/network uncertainty until a successful response. A new user message receives a new key.
- Added migration `f19b2c4d6e81` for `chat_requests`; migration round-trip/check remains part of normal application CI.
- Provider/model pipelines remain completely separate. Stage 9 requires no live model, provider secret, network call, prompt tuning, or model-specific behavior.

### Stage 10 — complete

- Added local operational visibility for persisted idempotency state: `GET /api/chat-requests`, per-key detail, and a `/chat-requests` admin page showing request key, status, timestamps, requested conversation, linked run, original failure, and recovery ancestry.
- Added explicit manual recovery for `processing` and `failed` requests. Recovery never mutates/reopens the old record; it creates a distinct new request key using the original message/conversation and records `recovered_from_id` plus a required operator recovery note.
- Recovery requires an explicit duplicate-risk acknowledgement at the HTTP boundary. Completed requests cannot be recovered because their safe behavior is ordinary idempotent replay.
- Added migration `a31d7f4e9c20` for the recovery audit link/note. Upgrade/downgrade/autogenerate checks remain green.
- The same recovery key is itself idempotent: repeating an already-completed recovery returns the persisted run and never executes a second agent loop. Reusing that key with different recovery ancestry/note conflicts.
- Existing crash-like states are now operationally covered: reserved-without-run remains blocked, completed-run/lost-response safely replays from SQLite, failed execution remains terminal until an explicit new audited recovery attempt is created.
- Added a two-thread/two-session test against file-backed SQLite proving concurrent reservation of one request key lets exactly one operation execute while the other observes the processing reservation. Only one request record/run is persisted.
- Browser behavior is conservative for blocked keys: both HTTP 425 and 409 preserve the pending request/key in `localStorage`; the UI does not silently substitute a new key. Explicit recovery is performed from the Requests page.
- The full 40-case deterministic application scenario suite remains green after the operational changes. Python 3.12/3.13 tests and migration checks are green.
- Provider/model tests remain a separate optional pipeline. Stage 10 added no provider-specific application behavior and required no live-model call.

### Stage 11 — complete

- Added application-only SQLite storage tooling; no provider/model API, prompt behavior, or network dependency is involved.
- `create_backup` uses SQLite's native backup API against the active file-backed database rather than copying a live WAL-mode `.db` file. A regression test keeps committed data uncheckpointed in `-wal` and proves that the produced backup still contains it.
- Backups are staged in a same-directory temporary file, independently validated, fsynced, and atomically published. Existing destinations are never silently overwritten.
- `validate_database` opens the candidate independently and requires `PRAGMA integrity_check = ok`, zero `foreign_key_check` violations, and the exact runtime schema revision. Corrupt/non-SQLite candidates are normalized to `DatabaseValidationError`.
- Runtime schema compatibility no longer depends on finding `alembic.ini` beside an installed package. `CURRENT_SCHEMA_REVISION` is embedded in the storage layer, while a test requires it to equal the actual Alembic migration head.
- Restore validates the candidate before touching the active database, creates a distinct pre-restore safety backup, stages/validates the replacement, checkpoints WAL, atomically replaces the database, and validates the result. An unexpected post-replace validation failure attempts rollback from the safety copy.
- Pre-restore safety backup names include sub-second UTC precision so rapid consecutive operations do not collide.
- Restore is explicitly an offline operation: documentation requires the application to be stopped first because SQLite cannot reliably prove that another process is still holding a read-only descriptor to the old database inode.
- Added `inventory-portable-v1` JSON export for the implementation-independent inventory domain: nested categories/locations, items, aliases, tags, structured attributes, current locations, stable IDs/timestamps, and domain history events.
- Portable JSON deliberately excludes agent/evaluation/provider/experiment traces. Full SQLite backup remains the disaster-recovery format for conversations, chat idempotency/recovery audit records, evaluations, and all other application tables.
- Round-trip tests cover nested fixture state, aliases/tags/attributes, FTS search after restore, item history, conversation messages, chat-request recovery ancestry/note, corrupt-candidate rejection, backup overwrite protection, and schema-revision mismatch.
- Added canonical Just recipes: `storage-test`, `db-backup`, `db-validate`, `db-restore`, and `portable-export`.
- Stage 11 application CI is green on Python 3.12/3.13 and the unchanged 40-case deterministic scenario suite remains green. Provider/model pipelines remain separate and optional.

### Stage 12 — complete

- Added a strict `inventory-portable-v1` parser with explicit format rejection, duplicate-JSON-key detection, strict structural schemas, timezone-aware timestamp validation, positive stable IDs/quantity checks, and rejection of unknown serialized fields such as derived normalized names.
- Pure validation runs before any database or output-directory mutation. It rejects duplicate category/location/item/event IDs, dangling category/location/item/event references, self-parent links, hierarchy cycles, normalized duplicate sibling names, invalid item states, duplicate normalized aliases/tags, and inconsistent spellings of one normalized global tag.
- Portable import targets only a genuinely new SQLite path. Existing database files/sidecars and the configured active database are rejected; there is no merge mode and no overwrite flag.
- Import first migrates a private staging database to the current Alembic head. The migration environment supports an explicit programmatic URL override so an ambient `AH_THERE_IT_IS_DATABASE_URL` cannot redirect portable import toward the active database.
- Category, location, item, and event stable IDs plus audit timestamps are preserved. Names, descriptions, item state/quantity, structured attributes, aliases, tags, current locations, and domain history are reconstructed.
- Serialized derived state is not trusted. `normalized_name` values are recomputed with the current `normalize_name`; FTS5 is populated only by the current schema triggers. Import performs an explicit base-table-versus-FTS consistency check before commit.
- The staged database is independently validated, consolidated through SQLite's backup API so committed WAL state is captured, and published with atomic no-overwrite file creation.
- Added `import-json --dry-run` and normal `import-json` CLI flows plus canonical `portable-import-dry-run` and `portable-import` Just recipes.
- Tests cover every required ID/reference class, malformed structures, hierarchy failures, normalized duplicates, target safety, ambient migration-URL isolation, dry-run no-write behavior, deterministic search/FTS, exclusion of conversations/chat-request audit state, and semantic `export -> import -> export` equality apart from volatile `exported_at` and order-insensitive alias/tag sets.
- Full SQLite backup/restore remains the only full-fidelity disaster-recovery path. Portable import remains inventory/history-only and adds no provider/model, voice, Telegram, images, QR, MCP, PWA, cloud sync, embeddings, or multi-user behavior.
- Stage 12 local verification completed with the storage suite, migration check, full project test suite, and deterministic scenario pipeline; GitHub CI remains the merge gate.

### Stage 13 — complete

- Added a committed hand-authored `inventory-portable-v1` compatibility fixture independent of the current exporter, with fixed IDs/timestamps, nested inventory state, history, and the older real Alembic revision `c4cfe3a3e921`.
- Added an executable fixture -> validate -> import into current schema -> SearchService -> re-export compatibility test.
- Portable v1 semantic round-trip now protects stable category/location/item/event IDs, audit timestamps, hierarchy, state/quantity, attributes, aliases/tags, current references, and history payload/text/location references while treating alias/tag ordering as non-semantic.
- Re-export intentionally refreshes `exported_at` and records the current database revision; the archived `source.alembic_revision` remains import metadata only and never selects source-schema code.
- Parsing now has an explicit format-version dispatch boundary. `inventory-portable-v1` remains frozen and unsupported/future identifiers remain explicit validation errors rather than permissive v1 extensions.
- Current normalized/FTS state is reconstructed from imported base data and verified through normal SearchService queries.
- Full SQLite disaster recovery remains separate and operational/chat/evaluation/provider state remains outside the portable compatibility contract.
- Stage 13 passed the complete provider-independent application/migration/scenario pipeline plus provider adapter contract on Python 3.12/3.13 CI.

### Stage 14 — complete

- Moved the existing Alembic environment and unchanged revision history under installed `ah_there_it_is` package resources.
- Added one packaged migration configuration/runner boundary using an explicit database URL; ambient `AH_THERE_IT_IS_DATABASE_URL` cannot redirect programmatic upgrade/import targets.
- Routed portable import through the packaged migration runner, preserving the Stage 12-13 non-destructive reconstruction contract outside a source checkout.
- Added explicit database upgrade and migration-check CLI/Just surfaces without introducing automatic migration during application import/startup.
- Source-development Alembic configuration now points at the packaged migration tree while preserving normal migration authoring/check workflows.
- Packaging metadata includes migration resources and a real wheel smoke test proves fresh migration plus portable-v1 import/search from a wheel installation in an unrelated working directory.
- Final Stage 14 verification passed the complete deterministic application/migration/scenario/provider-contract pipeline and Python 3.12/3.13 CI. No provider/model behavior or dependency/runtime policy was changed.

### Stage 15 — complete

- Added typed deterministic read-only location suggestions for items whose stored current location is unknown.
- Suggestions derive only from the item's own location history plus current locations of related items sharing category and/or tags; no provider/model reasoning, embeddings, external data, or invented probability is involved.
- Known `Item.current_location_id` remains authoritative. Items with a known current location do not receive inferred alternatives.
- Candidate ranking is stable and evidence-bearing, including last-known, same-category, shared-tag, combined evidence, aggregation, and deterministic tie handling.
- Added resolved-item-only `suggest_item_locations`; returned location IDs may become seen for read inspection but are not made resolved or mutation-authorized by suggestion.
- Replay capability reconstruction preserves the same seen-not-resolved authorization boundary.
- Provider-independent corpus/scenario coverage expanded from 40 to 42 cases with persisted-state/event checks proving suggestion turns remain read-only.
- No schema migration, persistent suggestion state, prompt/provider/runtime/dependency/workflow change, or portable/storage semantic change was introduced.

### Stage 16 — complete

- Added separate strict `inventory-bootstrap-v1` onboarding format and parser/semantic validation boundary; it is not portable recovery.
- Bootstrap manifests use component-array location/category paths and carry no IDs, normalized/search state, timestamps, events, migration revision, or operational/provider data.
- Database-aware preflight requires the active database to exist at the current schema and all seven inventory-domain tables to be empty; operational tables are ignored and preserved.
- Apply creates hierarchy/items through `InventoryService(autocommit=False)` in one transaction, so IDs, normalization, FTS, timestamps, aliases/tags, and `item_created` events are generated by current code with explicit bootstrap provenance.
- No merge/upsert/overwrite/partial mode or automatic database migration was added.
- Added bootstrap preflight/apply CLI and Just surfaces plus a hand-authored fixture and rollback/search/FTS/portable-export integration coverage.
- Final Stage 16 verification passed 195 tests, migration/corpus/scenario/provider-contract checks, all 42 deterministic scenarios, and Python 3.12/3.13 CI.

### Stage 17 — complete

- Added installed `ah-there-it-is serve` console entry point with explicit host/port parsing and loopback-only defaults.
- Added a read-only runtime schema gate requiring an existing file-backed SQLite database whose Alembic head set exactly equals the packaged migration heads before Uvicorn starts.
- Missing, uninitialized, behind, ahead, or incompatible databases are rejected without creation or migration; explicit upgrade remains operator-owned.
- Removed module-level application/Jinja runtime construction; `create_app()` is the true factory and development `just serve` uses Uvicorn factory mode with reload.
- Real wheel smoke now verifies console metadata plus installed-package health/index/static serving from outside the checkout and clean shutdown.
- No schema/data-format/provider/dependency/runtime/workflow or deployment-service behavior changed.
- Final Stage 17 verification passed 210 tests, all 42 deterministic scenarios, provider contract, and Python 3.12/3.13 CI.

### Stage 18 — complete

- Added stdlib-only deterministic per-user data-home resolution for Unix/XDG, macOS, and Windows plus `AH_THERE_IT_IS_DATA_DIR` override.
- Default database is now `<data-home>/inventory.db` and is independent of process CWD; non-blank `AH_THERE_IT_IS_DATABASE_URL` remains authoritative.
- Relative data-home bases/overrides are anchored to the user home rather than CWD, and whitespace-only overrides are treated as unset.
- Settings/import/create-app/runtime-schema/`paths` reads remain side-effect-free; only explicit storage upgrade creates a missing SQLite parent/database.
- Added read-only installed `ah-there-it-is paths` JSON output without exposing explicit non-file database credentials.
- Real wheel smoke proves explicit upgrade from one working directory and installed serve from another use the same stable default DB without stray CWD database/WAL/SHM files.
- Final Stage 18 verification passed 225 tests, all 42 deterministic scenarios, provider contract, and Python 3.12/3.13 CI with no implementation or CI correction rounds.

### Stage 19 — complete

- Added deterministic target-scale test data with exactly 1000 items, 200 nested locations, representative category hierarchy, aliases/tags/attributes/descriptions, ambiguity, and suggestion targets.
- Item search now discovers a bounded SQL/FTS candidate pool and applies the existing deterministic Python ranking only to candidate Items instead of materializing the full inventory.
- Location suggestions select only same-category/shared-tag evidence rows rather than hydrating all located Items.
- Added the single reverse tag lookup index `ix_item_tags_tag_id` through revision `b62f9d8a3c41`.
- `/items` now uses deterministic pagination with 50 default / 100 hard maximum, total/page metadata, and previous/next navigation.
- Location/category direct item counts use grouped SQL with bounded query counts rather than per-node lazy loads.
- Structural scale tests prove bounded ORM/query work without machine-dependent timing gates; all existing 42 application scenarios remain unchanged and green.
- Final Stage 19 verification passed 230 tests, migration/corpus/scenario/provider-contract checks, Python 3.12/3.13 CI, and required real-wheel coverage.

### Stage 20 — complete

- Added a typed read-only active-database doctor covering SQLite integrity/FK/exact schema plus normalized identities, hierarchy cycles, item state/quantity, semantic names, and FTS schema/content.
- Installed `ah-there-it-is doctor` returns machine-readable JSON and stable healthy/unhealthy exit behavior without creating, checkpointing, repairing, or otherwise mutating the database.
- Supported duplicate Item identities are reported as non-fatal warnings rather than being misclassified as corruption.
- Extracted bounded reusable FTS consistency diagnostics shared by portable import and doctor.
- Added explicit `repair-search-index`, which revalidates authoritative/base invariants in its write transaction, restores only current FTS objects/content, reruns doctor, and is idempotent.
- Search repair refuses authoritative/base corruption and preserves all non-FTS application tables/rows.
- Deterministic tests cover normalized/tree/state/quantity/FTS corruption, WAL/read-only behavior, 1000-item scale, portable import, repeat repair, and installed-wheel CLI behavior.
- Final Stage 20 verification passed 247 tests, all 42 deterministic scenarios, provider contract, migration checks, and Python 3.12/3.13 CI.

### Stage 21 — complete

- Added service-owned Category/Location rename, description and safe reparenting with stable IDs, duplicate-sibling rejection, and cycle prevention.
- Added browser/API Item creation and full Item correction for aliases, tags, attributes, category, location, description, state, quantity, and name.
- Added Category/Location create/edit browser flows with full-path parent choices.
- Kept browser writes behind `InventoryService`, preserving normal Item history provenance, atomicity, duplicate prevention, and trigger-maintained FTS.
- Installed-wheel coverage includes the new templates/static assets; target-scale item pagination remains unchanged.
- Final Stage 21 verification passed 254 tests, all 42 deterministic scenarios, provider contract, migration checks, Python 3.12/3.13 CI, with no post-PR corrections.

### Stage 22 — complete

- The browser Item search delegates ranking and FTS to `SearchService.search_items()`, caps results at 100, and leaves blank queries on the existing paged catalog.
- Read-only Location and Category detail pages show full paths, parent/child navigation, descriptions, and paged direct Items.
- Item search/catalog/detail and tree lists link through stable IDs without changing create/edit behavior.
- At the 1000-item / 200-location fixture, browser reads remain bounded; tree detail selects direct Item columns without materializing Item entities.
- Final Stage 22 verification passed 263 tests, all 42 deterministic scenarios, migration/corpus/provider-contract checks, and installed-wheel coverage.

### Stage 23 — previous plan superseded before execution

Assignment 0012 proposed a read-only browser Activity timeline. External architecture/write-safety audit performed after the seed identified higher-priority agent mutation safety gaps and a historical-path truth issue that should be resolved before expanding Activity.

- Assignment 0012 was not implemented.
- Its immutable seed remains preserved in history.
- Review record: `agent-tasks/reviews/0012-r0.md`.
- The Activity concept is deferred until historical evidence semantics are trustworthy.
- The next Stage 23 plan is issued separately under Assignment 0013.

### Stage 23 — complete (Assignment 0013)

- `move_item.location_id` is required but nullable: omission fails validation, explicit null remains an intentional take.
- Agent writes require database-wide unique Item canonical/alias identity or an exact Location/Category full path or globally unique leaf. Weak search matches and result truncation remain read-only.
- Each existing-ID reference is rechecked from its saved query after taking SQLite's write lock and before the service mutation in the same transaction; current-run created IDs retain frozen-capability behavior.
- Read ranking and result order are unchanged. Five deterministic write scenarios now search exact full paths.
- Focused dispatcher/provider/atomicity tests, 284 project tests, 42/42 scenarios, migration, corpus, and provider-contract checks passed locally.
- Review record: `agent-tasks/reviews/0013-r1.md`.

### Stage 24 — complete (Assignment 0014)

- A mutation-tool error ends the agent turn immediately; after the first changed mutation any tool error or empty final response rolls back the turn. Read errors before a change remain correctable.
- Failed turns keep diagnostic run logs but contribute no normal conversation messages or committed receipts.
- Typed compact mutation receipts record backend-observed changes, stable IDs and produced Event IDs. No-op Item updates/moves report `changed=false` without an Event.
- A packaged migration persists committed receipts; chat responses and completed idempotent replay expose `changes_applied` and those receipts independently of assistant text.
- Focused and full verification passed: 295 tests, 42/42 deterministic scenarios, migration/corpus/scenario/provider checks and installed-wheel coverage.
- Review record: `agent-tasks/reviews/0014-r1.md`.

### Stage 25 — complete (Assignment 0015)

- Keyed chat requests retain a durable pre-execution reservation, while one coordinator-owned final commit persists business changes, successful messages, completed run, mutation receipts, and completed request linkage together.
- Failed pre-commit work rolls back before separately marking the reservation failed. Uncertain final commits are reconciled from durable state in a fresh session: valid completion replays, uncommitted processing becomes an explicit failure, and inconsistent state is preserved for operator review.
- Same-key concurrency, response loss, injected before/after-commit faults, conflict and explicit recovery behavior are covered without automatic retry or expiry. A local two-connection probe observed that SQLite blocks a second writer after the first flushed write.
- Focused and canonical verification passed: 301 tests, 42/42 deterministic scenarios, migration/corpus/scenario/provider checks. Review record: `agent-tasks/reviews/0015-r1.md`.

### Post-Stage-25 hardening — Assignment 0016 complete

- Item Event history and direct Location Items now have bounded service pages (50 default, 100 maximum) with stable ordering and total/navigation metadata. Agent history/location tools return page objects; only the returned Location Item page expands seen capabilities.
- Item-detail history uses the same bounded read boundary and provides previous/next history links without hydrating the full Event collection. Existing internal unbounded helpers remain outside request paths.
- Structural tests with 1000 Events and 351 direct Items check page-only ORM materialization and bounded statement counts; browser navigation, tool schemas, replay capabilities and installed-wheel assets are covered.
- Focused and canonical verification passed: 308 tests, 42/42 deterministic scenarios, migration/corpus/scenario/provider checks. Review: `agent-tasks/reviews/0016-r1.md`.

### Post-Stage-25 hardening — Assignment 0017 complete

- `LLMClientInfo.config` now explicitly carries only intentional non-secret evaluation metadata. OpenAI-compatible and Gemini adapters retain stable timeout/retry/temperature/transport fields, persist base URLs without userinfo/query/fragment, and record only a boolean for configured extra request body rather than copying its values.
- Provider request bodies remain unchanged. New run metadata groups deterministically while historical rows remain readable without migration or redaction.
- Malicious URL and nested-body tests cover persisted run metadata, evaluation rendering, provider request preservation and historical config compatibility.
- Focused and canonical verification passed: 311 tests, 42/42 deterministic scenarios, migration/corpus/scenario/provider checks. Review: `agent-tasks/reviews/0017-r1.md`.

### Post-Stage-25 hardening — Assignment 0018 complete

- Explicit `restore-rehearsal` exercises the real restore path against an isolated, migrated and doctor-healthy fake active SQLite database. The configured active path is only compared with the candidate; its database, WAL and sidecars are not opened for writes, checkpointed or replaced.
- Machine-readable mechanics, physical integrity/FK/schema and application doctor outcomes distinguish invalid, wrong-revision and semantically unhealthy candidates. Exit status is successful only when all three pass; temporary replacement, sidecar and safety files are removed on all paths.
- Healthy, corrupt, wrong-revision, doctor-unhealthy, WAL candidate, active-byte-preservation, cleanup and installed-wheel CLI tests passed.
- Focused and canonical verification passed: 317 tests, 42/42 deterministic scenarios, migration/corpus/scenario/provider checks. Review: `agent-tasks/reviews/0018-r1.md`.

### Post-Stage-25 hardening — Assignment 0019 complete

- Newly-created Item Events store versioned `_history_evidence` snapshots for relevant Location and Category paths at the mutation boundary, while retaining stable foreign keys and existing payload fields.
- Tree rename/reparent leaves prior snapshots unchanged; legacy Events without snapshots remain readable. Bootstrap Events use the same service behavior, and portable-v1 preserves the snapshot payload exactly.
- No schema migration or backfill was added. Focused and canonical verification passed: 319 tests, 42/42 scenarios with 98 persisted-state checks, and 23 provider-contract tests.
- Review: `agent-tasks/reviews/0019-r1.md`.

### Post-Stage-25 hardening — Assignment 0020 complete

- Added read-only `/activity` and `/activity/{event_id}` pages with exact Event-type/Item-ID filters, deterministic newest-first paging, filter-preserving navigation, detail links, payload and original text.
- `ActivityService` owns bounded Event queries and projections; each Activity page selects at most 100 Event rows and joins surviving Item names without hydrating an unbounded history.
- Event-time Location/Category snapshot paths are rendered as historical evidence. Legacy Location paths are labeled current with historical path unavailable; null/deleted Item links are handled without replacement identity.
- Item-detail history links to Activity detail and retains its existing bounded ordering and pagination.
- Structural coverage includes 1000+ Events, tied timestamps, combined filters, unknown IDs, snapshot/legacy rendering, navigation, and installed-wheel Activity templates/route.
- Focused Activity/target-scale checks and final canonical verification passed: 322 tests, migration-check, 42-case corpus/scenario checks, 42 completed scenarios with 98 persisted-state checks and zero failures, provider-contract (23 tests).
- Review: `agent-tasks/reviews/0020-r1.md`.

### Post-Stage-25 hardening — Assignment 0021 complete

- Agent context now loads at most the newest 40 persisted messages using a descending SQL `LIMIT`, restores chronological order, and drops a leading assistant message when the retained boundary splits a turn. System and current user messages remain outside the cap.
- Full conversation history and persisted messages are unchanged. Agent run logs preserve the exact initial system, bounded prior context, and current user messages sent to the LLM; failed turns remain excluded from later context.
- Structural coverage seeds 1000 messages and verifies the bounded query, sent context, run log, and intact full history. No schema migration or summarization policy was added.
- Focused and canonical verification passed: 324 tests, migration/corpus/scenario checks, 42 completed scenarios with 98 state checks and zero failures, and 23 provider-contract tests. Review: `agent-tasks/reviews/0021-r1.md`.

### Post-Stage-25 hardening — Assignment 0022 complete

- Installed `ah-there-it-is serve` keeps its `127.0.0.1` default and rejects non-loopback hosts unless each start explicitly supplies `--allow-nonlocal`. The guard recognizes IPv4 `127.0.0.0/8`, IPv6 `::1`, and case-insensitive `localhost`.
- Explicit non-loopback opt-in emits an unauthenticated-exposure warning to stderr. The check runs before schema validation and Uvicorn; no environment bypass, schema changes, or `just serve` override were added.
- Runtime and installed-wheel coverage exercises loopback classification, wildcard/LAN/public hosts, refusal ordering, warning and opt-in behavior. Focused and canonical verification passed: 339 tests, migration-check, 42-case corpus and scenarios, 42/42 scenario completion with 98 checks and zero failures, and 23 provider-contract tests.
- Review: `agent-tasks/reviews/0022-r1.md`.

### Post-Stage-25 hardening — Assignment 0023 complete

- Added an offline retrieval evaluator and versioned semantic-label corpus with 86 cases: 28 English, 27 Russian, and 31 Ukrainian. The cases cover names, aliases, separators and apostrophes, mixed tokens, tags, attributes, duplicate names, and no-match queries.
- Current SearchService passes all 86 gating cases. The JSON report records per-language totals and each case's result IDs, match types, scores, and failure reasons.
- A separate non-gating candidate-starvation diagnostic uses 35 distractors. For `blue box`, the target is at FTS rank 36, beyond the bounded candidate pool of 20, and is absent from the top five.
- Non-gating observations record an English typo, Russian transliteration, Ukrainian inflection, and a Ukrainian U+02BC apostrophe variant. The first three targets are not returned; the U+02BC target is surfaced through FTS on this fixture.
- Added the `retrieval-eval` Just recipe and invoked it in the existing application CI job. No search policy, database schema, or dependency changes.
- Focused and canonical verification passed: 39 focused SearchService/evaluation tests, 342 total tests, migration-check, corpus/scenario checks, 42/42 scenarios with 98/98 state checks, retrieval 86/86, and provider-contract (23 tests).
- PR #47 passed its single `verify` check on implementation head `da110105b138f45e8e86b965235da74a1abfa7b5`; CI correction iterations: 0.
- Review: `agent-tasks/reviews/0023-r1.md`.

### Stage 26 complete — Assignments 0024–0028

The Stage 26 location-truth design is delivered across domain/storage, portable-v2, agent tools and deterministic scenarios, suggestions, and browser UX. Item condition/state and Location status are independent. The browser displays known Location links, location unknown, taken/in-use, and terminal not-applicable states explicitly; condition unknown has its own label. Manual move, take, mark-unknown, discard, sold, and reactivation forms use InventoryService transitions. A blank Items catalog defaults to active Items and supports lifecycle and location-unknown filters; search includes terminal Items by default. Suggestions appear only for unknown Location and are labeled as inferred evidence. Activity preserves event-time path snapshots and renders new transitions. Assignment 0028 focused tests and the full verification suite passed: 360 tests, 58/58 scenarios, 86/86 retrieval cases, 23 provider-contract tests, migration and corpus checks. Review: `agent-tasks/reviews/0028-r1.md`.
