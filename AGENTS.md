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

### Stage 5 — next

Connect a real replaceable model provider and turn the Stage 4 evaluation data into an experiment/replay workflow:

1. Add the first real LLM adapter only in an environment where its API can actually be exercised; prefer a small OpenAI-compatible/provider-neutral HTTP boundary rather than introducing an agent framework.
2. Keep provider/model/temperature/reasoning/tool settings in explicit adapter metadata so every run remains attributable and comparable.
3. Add a prompt experiment runner that selects rated historical runs, applies a named prompt variant, and stores results as separate experiment runs without overwriting production history.
4. Start with replay against captured input/tool evidence and explicitly mark divergence when a variant requests a tool/result not present in the recorded trace; do not pretend this is an exact historical DB snapshot.
5. Add side-by-side baseline/variant comparison and aggregate metrics: average human rating, completion/failure rate, tool rounds, ambiguity/clarification rate, and mutation-error rate.
6. Add a compact review UI for choosing which variant response is better; keep human ratings authoritative rather than deriving a fake quality score from model self-evaluation.
7. Add prompt files under a versioned project directory and make prompt changes reviewable in git.
8. Expand the heuristic/offline tests only for protocol behavior; do not grow the heuristic parser into a shadow production NLP implementation.
9. Once a real model is connected, build a representative 30–50 query evaluation corpus from actual inventory usage before tuning prompts or adding embeddings.
10. Keep voice, Telegram, images, MCP, QR, and PWA out of scope until the real text workflow and evaluation loop are stable.
