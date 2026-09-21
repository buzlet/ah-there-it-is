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
- Do not add dependencies that cannot be exercised in the active development environment.
- Keep module imports side-effect-light; application creation belongs in `create_app()`.
- Preserve local-first operation. External LLM APIs may be adapters, never storage authorities.
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
- Minimal `Conversation`/`Message` persistence stores only human-visible user/final-assistant turns needed for clarification across requests; internal tool traces are intentionally ephemeral.
- `ScriptedLLMClient` provides deterministic complete offline agent tests.
- `HeuristicLLMClient` provides a deliberately tiny offline smoke adapter for `Где X?` and `Положил/переложил X в Y`; it is development scaffolding, not a production NLP model.
- No real model-provider adapter was added because the active sandbox cannot exercise an external API. The provider boundary is ready for one later.
- `Justfile` now includes dedicated `test-agent` and `migration-check` recipes in addition to the canonical test/check/migrate/server commands.

### Stage 4 — next

Build the first usable text-only web application around the proven agent core:

1. Add application-level session/DB dependencies and an `AgentRunner` factory; HTTP handlers must remain thin.
2. Add a text chat endpoint that accepts `message` plus optional `conversation_id` and returns the final response plus stable conversation ID.
3. Wire the existing minimal web page into a simple chat UI with no frontend framework requirement; preserve conversation ID between turns.
4. Use `HeuristicLLMClient` only as an explicit offline-development mode so the sandbox can exercise the whole UI; do not present it as normal language understanding.
5. Add a provider-selection/configuration seam, but add a real external provider adapter only when it can be tested in the active environment.
6. Add basic read-only inventory pages for items, locations, categories, and an item detail/history view so agent writes can be inspected manually.
7. Keep manual correction/edit controls minimal and service-backed; do not duplicate domain validation in HTTP/UI code.
8. Add HTTP/UI integration tests covering new conversation, continued clarification, agent errors, and persisted inventory effects.
9. Keep voice, Telegram, images, embeddings, MCP, QR, and PWA explicitly out of scope.
10. Finish with an end-to-end local smoke flow: enter text in the browser, mutate inventory through the agent, then find/read the stored item from the browser.
