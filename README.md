# Ah, There It Is!

Local-first inventory memory for finding physical things using natural-language messages.

## MVP architecture

- FastAPI web application
- SQLAlchemy 2 + SQLite persistence
- Alembic migrations
- deterministic exact/normalized/FTS5 candidate search
- provider-neutral bounded LLM tool loop
- Pydantic tool schemas
- Jinja2 + vanilla JavaScript text UI
- replay-oriented agent run logs and 1–5 human evaluation feedback
- controlled prompt/model replay against captured tool evidence

The LLM is not a database client. Domain services own validation, identity, history, and mutations. The live agent can mutate only stable IDs that the backend has resolved from prior tool results. Experiment replay never executes mutations against the live inventory database. Agent turns are transactionally atomic: mutation tools flush but do not commit independently; a successful final response commits the turn, while any failed turn rolls back its business mutations/history before the failure run is logged. Chat submissions can also carry a stable idempotency key: a completed retry returns the persisted run without invoking the LLM/tool loop again, while conflicting, still-processing, or previously failed keys are blocked rather than guessed/re-executed.

## Sandbox development

The project remains compatible with packages exercised in the OpenAI sandbox. The OpenAI-compatible adapter uses a persistent `httpx.Client` so multi-round tool loops reuse HTTP keep-alive connections without depending on a provider SDK.

Verified baseline:

- Python 3.13.5
- FastAPI 0.128.2
- Pydantic 2.13.4
- SQLAlchemy 2.0.50
- Alembic 1.18.4
- Jinja2 3.1.6
- pytest 9.0.2
- httpx 0.28.1
- uvicorn 0.48.0

`ruff` and `mypy` are not assumed because they are not currently available in the sandbox.

## Repeated commands

`Justfile` is the canonical interface:

```bash
just test
just test-agent
just test-web
just test-provider
just compile
just check
just migrate
just migration-check
just serve
just eval-export evaluation-cases.json
just experiment-replay strict-v2 prompts/inventory-v2-strict.txt inventory-v2 50
just provider-smoke
just live-compare baseline.json variant.json live-compare.json
just scenario-check
just scenario-eval
just provider-contract
just model-probe
just storage-test
just db-backup ah-there-it-is.backup.db
just db-validate ah-there-it-is.backup.db
just db-restore ah-there-it-is.backup.db
just portable-export inventory-export.json
just portable-import-dry-run inventory-export.json imported.db
just portable-import inventory-export.json imported.db
```

If `just` is unavailable in a constrained sandbox, execute the exact underlying recipe command rather than adding a network dependency to install it.

## LLM providers

Offline development still defaults to `HeuristicLLMClient`. Two real-provider adapters are available.

Native Google Gemini API / Gemma 4:

```bash
export AH_THERE_IT_IS_LLM_PROVIDER=gemini
export AH_THERE_IT_IS_LLM_PROVIDER_NAME=gemini
export AH_THERE_IT_IS_LLM_MODEL=gemma-4-31b-it
export AH_THERE_IT_IS_LLM_API_KEY=secret
export AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON='{"generationConfig":{"thinkingConfig":{"thinkingLevel":"HIGH"}}}'
```

The native Google adapter uses `generateContent` and provider-native `functionCall` / `functionResponse`. Provider-only opaque state such as thought signatures is round-tripped in memory and excluded from persisted generic tool-call DTOs. `generationConfig` extras are merged safely with ordinary configured values such as temperature instead of requiring model-specific branches in application code.

The manual Google model-probe job currently targets `vars.GEMINI_MODEL` (with `gemma-4-31b-it` as its fallback) and waits 3.2 seconds between every model request, including multi-step function-calling continuations. This keeps the probe below 20 RPM. The application pipeline has no such pacing because it never calls a network model.

For a hosted or local OpenAI-compatible endpoint:

```bash
export AH_THERE_IT_IS_LLM_PROVIDER=openai-compatible
export AH_THERE_IT_IS_LLM_PROVIDER_NAME=my-provider
export AH_THERE_IT_IS_LLM_BASE_URL=https://provider.example/v1
export AH_THERE_IT_IS_LLM_MODEL=model-name
export AH_THERE_IT_IS_LLM_API_KEY=secret
```

`AH_THERE_IT_IS_LLM_API_KEY` is used only for request authentication and is never written to run metadata. Optional request settings include `AH_THERE_IT_IS_LLM_TEMPERATURE`, timeout, and `AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON`.

## Retry-safe chat requests

`POST /api/chat` accepts an optional `request_key` (8–128 characters, URL/token-friendly characters only). A client that may retry should generate one key per logical user submission and reuse that same key until it receives the response.

The first request reserves the key in local SQLite **before** the LLM is constructed. Terminal behavior is deliberately conservative:

- same key + same message/requested conversation + completed request: return the original `conversation_id`, `run_id`, content, and round count with `replayed=true`;
- same key with different request content: HTTP 409;
- same key while the original is still `processing`: HTTP 425;
- same key after a failed execution: HTTP 409; use a new key only for an intentional new attempt.

There is intentionally no time-based automatic retry/expiry for `processing` records. If the server dies after a business commit but before the client receives the response, blindly expiring the key is exactly how duplicate mutations are born.

Stage 10 adds local operational inspection at `/chat-requests` plus read APIs under `/api/chat-requests`. A blocked `processing` or `failed` request may be recovered only through an explicit operator action that:

- requires acknowledgement of duplicate-execution risk and a written recovery note;
- creates a **new** request key instead of reopening or rewriting the old record;
- links the new record to the original with `recovered_from_id`;
- preserves both the original status/error and the recovery decision as an audit trail;
- refuses recovery of a completed record because completed requests should be replayed normally.

The browser stores the pending submission and key in `localStorage`. Reloading after an uncertain network result resends the same logical request, so a completed server-side operation is replayed from SQLite rather than executed twice. HTTP 425 and 409 leave that pending key in place; the browser does not silently invent a replacement key for a blocked request. Manual recovery is performed from the Requests page.

## Prompt/model evaluation

Every live agent run stores:

- prompt version and exact SHA-256 prompt hash
- full system prompt
- provider/model/config metadata
- initial message context
- per-round tool calls, model response metadata, and returned tool results
- completion/failure status and final response
- optional human rating from 1 to 5 plus a comment

Versioned prompts live under `prompts/`. `inventory-v1.txt` is tested to remain byte-for-byte identical to the built-in default prompt.

### Controlled replay

`just experiment-replay` selects rated historical runs unless explicit source run IDs are supplied. A prompt/model variant receives the original input messages with the new system prompt and may consume only the source run's captured tool results in their exact original order.

If the variant asks for a different search, arguments, tool order, or extra tool call, the experiment is marked `diverged`. No live inventory mutation is executed during replay. This is intentionally conservative: captured traces are evidence, not historical database snapshots.

The `/experiments` UI shows aggregate completion/divergence/failure metrics, rounds, human ratings, pairwise review counts, a simple clarification heuristic, and tool/mutation error rates. `/experiments/{id}` provides baseline-versus-variant review with `baseline`, `variant`, `tie`, or `both_bad` plus an optional 1–5 variant rating.

## Development pipelines

Application correctness and model/provider behavior are deliberately separate concerns.

### Application pipeline

Normal development uses `eval/scenarios-v1.json` and `ScenarioLLMClient`, not a network model. The scenario mock declares the model-side decisions while the real application still runs:

- `AgentRunner` and dynamic capability gating;
- deterministic search;
- real `ToolDispatcher` validation;
- real SQLite fixture state;
- real service-layer reads and mutations;
- history/event recording;
- multi-turn conversation state.

Scenario tool arguments can reference actual prior tool results, for example `${tool:search_items:result.0.id}`. IDs therefore come from the application's real search results rather than fixture constants. Scenarios can also require/forbid offered tools and assert facts about prior tool results. A broken search, wrong capability decision, failed mutation, or unexpected ambiguity fails deterministically.

`eval/scenarios-v1.json` covers all 40 cases in `eval/corpus-v1.json`. CI requires the scenario and corpus ID sets to remain identical. Every application scenario now also has at least one independent corpus postcondition. The shared provider-neutral checker verifies persisted location/null-location, state, quantity, description content, structured attributes, category absence, item existence, exact event-count deltas, typed item events with optional source/destination locations, history-event counts, and no-mutation invariants after the agent loop. `scenario-eval` fails if any case fails, any postcondition fails, or a selected application scenario has no postcondition; the current suite is 40/40 automatically checked.

Canonical commands:

```bash
just scenario-check
just scenario-eval
```

`.github/workflows/ci.yml` is the **application-ci** workflow. It has no model API secrets or live-model jobs. It runs ordinary tests on Python 3.12/3.13 plus the complete offline scenario suite.

### Provider/model pipeline

Provider adapters and real model behavior are tested independently of application business logic.

`model_probe.py` calls only the `LLMClient` contract with static `AgentMessage[]` and `ToolDefinition[]`. It does not create an inventory database, run `ToolDispatcher`, or execute mutations. The probe suite covers a single tool call with JSON arguments, multiple independent tool calls in one response, tool-result continuation, parallel-result continuation, and final plain text. Multi-round probes preserve the exact returned `ToolCall` object in memory, including provider-only opaque state, before feeding synthetic tool results into the next `LLMClient.complete()` call. This answers a narrow question: can a configured adapter/model obey the provider-neutral protocol the application actually requires?

Canonical commands:

```bash
just provider-contract
just model-probe
```

`.github/workflows/provider-contract.yml` runs local adapter-contract tests on push/PR. Real Groq/Gemini probes are manual `workflow_dispatch` jobs using the protected `live-llm-test` environment; they never gate application CI.

The older `live_eval` / `live_compare` tools remain available for deliberate end-to-end research and prompt/model experiments. Their results are evidence about a provider/model configuration, not a prerequisite for application development or correctness.

## Deterministic retrieval evidence

The executable scenario suite has already exposed application bugs without involving a real model:

- tree queries such as `Кабинет Шкаф` previously tied the intended node with descendants sharing the same ancestry tokens; `exact_path` now ranks the exact normalized path above descendant containment while bare `Шкаф` remains ambiguous;
- a two-token create search such as `DisplayPort-HDMI` previously returned an unrelated HDMI cable from OR-based FTS; multi-token FTS now requires at least two overlapping query tokens.

These fixes live in deterministic search and are model-independent.

## CI and external verification

Normal application CI receives no provider secrets. Provider secrets/variables remain confined to manual jobs in `.github/workflows/provider-contract.yml`:

- `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_BASE_URL`;
- `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_BASE_URL`.

Native Gemini and OpenAI-compatible adapters remain replaceable implementations behind the same `LLMClient` boundary. Provider-specific protocol work belongs in adapter/contract tests, not in inventory scenarios.


## Local backup, restore, and portable export/import

Stage 11/12 storage operations are application-only and require no LLM/provider access.

The active SQLite database may use WAL mode. **Do not copy the live `.db` file as a backup.** A committed transaction can still live in the WAL sidecar. Use the SQLite backup API through the canonical commands:

```bash
just db-backup ah-there-it-is.backup.db
just db-validate ah-there-it-is.backup.db
```

`db-backup` reads a transactionally consistent SQLite snapshot, including committed WAL content, writes it to a same-directory temporary file, independently runs SQLite integrity and foreign-key checks plus the exact Alembic-head check, then atomically publishes the validated backup. Existing destinations are not overwritten unless the CLI is invoked explicitly with `--overwrite`.

Restore is deliberately stricter:

```bash
# Stop the application first.
just db-restore ah-there-it-is.backup.db
```

Before replacing anything, restore validates the candidate and creates a separate pre-restore safety backup of the current database. It checkpoints the active WAL, stages and validates the replacement, and uses an atomic same-directory replacement. **The application must be stopped before restore** because SQLite cannot reliably prove that another process still has a read-only connection to the old inode.

For an implementation-independent inventory archive and reconstruction:

```bash
just portable-export inventory-export.json
just portable-import-dry-run inventory-export.json imported.db
just portable-import inventory-export.json imported.db
```

The versioned `inventory-portable-v1` JSON contains category/location trees, items, aliases, tags, structured attributes, current locations, and domain history events with stable IDs/timestamps. It intentionally excludes conversations, chat-request idempotency/recovery state, agent/evaluation/experiment traces, and provider metadata from reconstruction. SQLite backup remains the full-fidelity disaster-recovery snapshot for every application table.

Portable import is deliberately non-destructive. Validation is completed before any output database is created. The destination must be a new path, must not be the configured active database, and must not already contain a database or SQLite sidecars. There is no portable merge mode and no overwrite option. `portable-import-dry-run` performs the same strict document and target checks without creating the destination.

Import migrates a private staging database to the current schema, preserves portable stable IDs and audit timestamps, reconstructs the inventory/history domain, and recomputes normalized/search-derived state through current code and SQLite triggers. It verifies FTS against the reconstructed base tables, validates the staged database, captures WAL state through SQLite's backup API, and publishes the result without overwrite semantics.

The parser rejects unknown format identifiers, unknown structural fields, malformed section types, duplicate IDs, dangling parent/item/location references, self-parent links, hierarchy cycles, normalized duplicate sibling names, invalid states/timestamps, and other portable-domain integrity failures. `inventory-portable-v1` is a frozen compatibility contract: future portable formats must use an explicit format-version dispatch boundary and must not loosen or accumulate compatibility conditionals inside the v1 parser. A successful `export -> import -> export` is tested for semantic equality; `exported_at` is intentionally volatile and alias/tag list ordering is semantically irrelevant. Re-exporting an older v1 archive from a newly migrated database records the current database revision in `source.alembic_revision`; the older source revision remains import metadata and does not select migration code.


## Current scope

Stages 0–12 are complete. The application regression pipeline covers the full 40-case corpus with independent persisted-state/event postconditions, agent turns are transactionally atomic, chat submissions are retry-safe through persisted idempotency keys plus explicit audited recovery, and the local SQLite store has validated WAL-safe backup/restore plus bidirectional versioned portable inventory/history export/import. Provider/model compatibility remains a separate contract pipeline. Stage 13 will freeze `inventory-portable-v1` as a compatibility fixture/contract so future schema migrations cannot silently break old archives.

Voice, Telegram, images, QR, MCP, PWA, embeddings, and multi-user support remain out of scope until the text workflow is stable.
