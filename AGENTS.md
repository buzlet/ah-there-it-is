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

### Stage 6 — in progress

Preparation and first live-provider validation are complete:

- Added versioned `inventory-fixture-v1`, a deterministic realistic inventory graph used only for evaluation. Every live evaluation case starts from a fresh in-memory SQLite database; live user inventory is never reused or mutated.
- Added `eval/corpus-v1.json` with 40 representative Russian-language cases covering find, create, move, ambiguity/clarification, updates, history, nested locations, normalization/descriptive queries, and backend-safety attempts.
- Added typed corpus validation and `just corpus-check`; corpus IDs are unique and fixture compatibility is explicit.
- Added `live_eval` harness. It records exact corpus/fixture/prompt hash/provider/model config, runs multi-turn cases through the real `AgentRunner`, exports each run's full tool trace before the temporary database is discarded, performs simple state-based postcondition checks, and emits JSON suitable for comparison/archive. Cases without an automated postcondition are explicitly manual-review cases and are never counted as automatically passed.
- `live_eval` refuses the heuristic provider by default. `--allow-heuristic` exists only to test the harness offline and must not be treated as model-quality evidence.
- Added an offline harness test proving a complete fixture-backed tool/mutation flow without touching external state.
- GitHub repository `buzlet/ah-there-it-is` is synchronized from U24. The GitHub CLI token on U24 now includes the `workflow` scope, so normal code, workflow, and tag pushes are supported. Tags `v0.1.0` and `v0.2.0` are present remotely.
- GitHub Actions test matrix is green on Ubuntu 24.04 / Python 3.12 and 3.13. `migration-check` is self-contained and upgrades a temporary SQLite database before running `alembic check`.
- A concrete deterministic-search weakness was exposed by the intentionally dumb heuristic adapter: Russian morphology such as `стола` vs stored `стол` is not normalized by Stage 2 search. Keep the realistic corpus wording; a real LLM should normally reformulate the search tool query. Treat recurring failures here as evaluation evidence before adding stemming/embeddings.
- Added a native Gemini `generateContent` adapter using only the Python standard library. Do not route Gemini through the OpenAI-compatible adapter: Gemini 3 function calling requires exact `thoughtSignature` preservation inside the current tool loop. Provider-only opaque state is kept in-memory and excluded from persisted generic tool-call traces.
- Gemini function declarations use `parametersJsonSchema`; Pydantic local `$ref` values are resolved and schemas are reduced to a provider-friendly JSON Schema subset before sending. Backend Pydantic validation remains authoritative.
- Live U24 verification on 2026-09-21 confirmed the supplied key/model endpoint and native function calling. GitHub Actions then completed full real `AgentRunner` loops: `find-01` and `find-02` each performed search -> stable-ID read -> final answer with correct fixture locations. This live-verifies the multi-round functionCall/functionResponse path.
- GitHub Actions live testing uses the protected `live-llm-test` Environment plus manual `provider` and `suite` choices. Gemini uses `GEMINI_API_KEY`, `GEMINI_MODEL`, and `GEMINI_BASE_URL`; Groq uses `GROQ_API_KEY`, `GROQ_MODEL`, and `GROQ_BASE_URL`. `smoke` runs `find-01` + `move-01`; `representative` additionally runs `create-01`, `ambiguity-01`, and `history-01`. Ordinary CI jobs receive no provider secrets, and the selected live job receives only its provider's secret.
- First five-case live run: 2 completed correctly; 3 failed on provider `503 high demand`. A subsequent retry-enabled run exposed the free-tier request quota: `gemini-3.8-flash` returned `429 RESOURCE_EXHAUSTED` with `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit 20. Failed provider runs must never count as passed merely because a no-mutation postcondition stayed true.
- Gemini transport retries are bounded and logged in provider config. Retry transient network/timeout and 5xx failures; do not retry HTTP 429 blindly because hard quota errors only waste requests/time. OpenAI-compatible transport also has bounded retries and explicit API-client headers; Groq/Cloudflare otherwise rejects Python urllib's default signature with Error 1010. Live jobs use a 30-second request timeout, max 2 transient retries, and 6-minute job limit. `live_eval` exits non-zero on provider/harness failures while still writing its report for artifact upload.
- Groq `qwen/qwen3.8-27b` live smoke on 2026-09-21 completed `find-01` and `move-01` with 2/2 automatic checks passing. `find-01` used 2 rounds. `move-01` used 5 rounds: an initial move was safely rejected because a broad `search_locations("стол")` had not unambiguously resolved the target; the model refined to `search_locations("Средний ящик")` and then moved successfully. This is expected backend safety behavior, not a duplicate mutation.
- Transport/rate-limit investigation replaced per-request `urllib` with persistent `httpx.Client` for OpenAI-compatible providers. A measured Groq round took 0.284 s client wall for 0.156 s provider server time, confirming the model is fast when not rate-limited. Provider metadata now separates client wall time, provider server time, attempts, and retry events.
- Groq exposed 7000 ITPM and 1000 OTPM limits. Live Qwen config now uses `reasoning_effort=none` and `max_completion_tokens=256`; 2048 was rejected because the expected output budget exceeded OTPM. Tool schemas are compacted and capability-gated so the first round exposes only search tools and later rounds expose only operations whose backend preconditions are reachable.
- Real `move-01` evidence exposed a deterministic retrieval miss for `search_locations("средний ящик стола")`. Tree search now preserves all original exact/path rules first, then uses reverse leaf-in-natural-phrase containment only as a zero-result fallback. The final Groq smoke completed `find-01` in 3 rounds / 1.374 s and `move-01` in 3 rounds / 10.294 s; the mutation was correct and the remaining ~9 s delay was one successful 429 `Retry-After`, not model inference.
- A five-case representative Groq run then completed find, move, ambiguity, and history correctly but exposed `create-01`: broad OR-based FTS produced unrelated single-token matches, the model explored unnecessary taxonomy, and exact string-order matching forced a redundant search before creation. Long multi-token FTS queries now filter candidates sharing fewer than two tokens; create tool descriptions forbid invented optional metadata/taxonomy; prior creation search accepts the same normalized token multiset in a different word order. A targeted real rerun completed `create-01` in 3 rounds / 1.362 s with no retries, correct location, `state=unknown`, and no invented category/tags/description.
- Controlled replay now rebuilds dynamic tool capability state from captured evidence instead of freezing round-1 definitions. This preserves Stage 5 replay safety while remaining compatible with Stage 6 capability-gated tools; replay still never executes live mutations.
- Evaluation and experiment summaries now include a SHA-256 fingerprint of canonical provider config and group by exact config as well as prompt/provider/model. Historical runs with different temperature/reasoning/token settings are therefore no longer silently mixed.
- Added a provider-neutral `live_compare` report for two live-eval JSON artifacts. It requires the same corpus/fixture, surfaces whether provider/model/config/case sets match, and reports per-case status/check changes, rounds, token counts, client/provider time, retry delay, tool usage/errors, and both assistant texts. It intentionally has no automatic winner or ranking.
- Manual GitHub live evaluation now has an explicit `prompt_variant` choice (`v1` or `v2-strict`); artifact names include the prompt variant so reports cannot silently overwrite each other. Historical replay now closes persistent provider clients after each source run.
- A same-config five-case Groq comparison is archived at `eval/results/2026-09-22-groq-v1-v2-representative.md`. With identical provider/model/config/corpus/fixture/case set, `inventory-v1` completed/passed 2/5 while `inventory-v2-strict` completed/passed 5/5. The v1 failures were provider-side invalid tool generations (`find_items`, `find_item`, malformed `create_item.aliases`); v2 used valid tool names/schemas in all five cases. `move-01` also reduced from 7 to 3 rounds and from 2 tool errors to zero. Treat this as a strong tool-discipline signal, not a winner: it is one stochastic sample at temperature 0.6.
- Manual review remains required before changing the default prompt. In v2 `ambiguity-01`, the model safely listed both candidates but then suggested an “основной” candidate instead of asking an explicit clarification question; automated no-mutation checks cannot judge that conversational choice.
- Live evaluation now supports repeated trials from fresh fixtures. Each result records `trial` and `execution_id`; `live_compare` keys by `(case_id, trial)` while treating old reports as trial 1. GitHub adds a quota-conscious `tool-discipline` suite (`find-01`, `create-01`, `ambiguity-01`) plus `repetitions=1|2|3` so prompt/tool reliability can be sampled without rerunning unrelated cases.

Remaining Stage 6 work requires usable provider quota:

1. Human-review the archived v1/v2 representative answers, especially ambiguity handling, and record 1–5 / baseline-vs-variant decisions instead of relying only on automated checks.
2. Repeat a small tool-discipline subset before changing the default prompt. If invalid tool names/schema recur under v1 but not v2, promote the strict prompt on evidence; if both remain stochastic, test a lower tool-calling temperature as a separate provider-config experiment.
3. Expand the corpus in small quota-aware batches toward all 40 cases. Stop and fix recurring deterministic retrieval/tool-contract errors before spending calls on the next batch.
4. Use exact prompt hash + provider/model/config fingerprint for every comparison and inspect divergences rather than aggregating unlike runs.
5. Change prompt/tool descriptions or deterministic retrieval only where the real corpus shows a recurring error pattern.
6. Reconsider embeddings only if real descriptive queries fail after sensible model reformulation.
7. Keep voice, Telegram, images, QR, MCP, PWA, and multi-user support out of scope until the live text workflow reaches a stable evaluation baseline.
