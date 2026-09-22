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

### Stage 9 — next

Make chat requests safe under client/network retries:

1. Add an optional stable client request/idempotency key to the chat API and agent execution boundary.
2. Repeating the same key with the same conversation/message must return the already-recorded result instead of invoking the LLM/tool loop or duplicating mutations.
3. Reusing a key with conflicting request content must fail explicitly rather than silently returning unrelated data.
4. Persist idempotency state locally with the conversation/run record; do not require Redis or another network service for the single-user MVP.
5. Cover create, move, and update retries with deterministic `ScenarioLLMClient` tests and exact event-count assertions.
6. Ensure browser retry/reload behavior can safely reuse the key while a genuinely new user message receives a new key.
7. Keep provider/model probes separate and optional. Idempotency is an application concern and must be testable with no network model.
8. Continue deferring additional channels and embeddings until the core text workflow is both atomic and retry-safe.
