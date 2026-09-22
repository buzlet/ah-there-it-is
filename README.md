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

The LLM is not a database client. Domain services own validation, identity, history, and mutations. The live agent can mutate only stable IDs that the backend has resolved from prior tool results. Experiment replay never executes mutations against the live inventory database.

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
```

If `just` is unavailable in a constrained sandbox, execute the exact underlying recipe command rather than adding a network dependency to install it.

## LLM providers

Offline development still defaults to `HeuristicLLMClient`. Two real-provider adapters are available.

Native Gemini `generateContent`:

```bash
export AH_THERE_IT_IS_LLM_PROVIDER=gemini
export AH_THERE_IT_IS_LLM_PROVIDER_NAME=gemini
export AH_THERE_IT_IS_LLM_MODEL=gemini-flash-latest
export AH_THERE_IT_IS_LLM_API_KEY=secret
```

The Gemini adapter uses the native REST protocol, including `functionCall` / `functionResponse` IDs and Gemini 3 `thoughtSignature` round-tripping during the active tool loop. Opaque provider state is deliberately excluded from persisted tool-call DTOs.

For a hosted or local OpenAI-compatible endpoint:

```bash
export AH_THERE_IT_IS_LLM_PROVIDER=openai-compatible
export AH_THERE_IT_IS_LLM_PROVIDER_NAME=my-provider
export AH_THERE_IT_IS_LLM_BASE_URL=https://provider.example/v1
export AH_THERE_IT_IS_LLM_MODEL=model-name
export AH_THERE_IT_IS_LLM_API_KEY=secret
```

`AH_THERE_IT_IS_LLM_API_KEY` is used only for request authentication and is never written to run metadata. Optional request settings include `AH_THERE_IT_IS_LLM_TEMPERATURE`, timeout, and `AH_THERE_IT_IS_LLM_EXTRA_BODY_JSON`.

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

## CI and external verification

`.github/workflows/ci.yml` runs the canonical `just` checks on Ubuntu 24.04 with Python 3.12 and 3.13. The manual `live-gemini-smoke` job uses the protected GitHub Environment `live-llm-test`. Configure there:

- `GEMINI_API_KEY` as an **Environment secret**;
- `GEMINI_MODEL` and `GEMINI_BASE_URL` as Environment variables;
- `GROQ_API_KEY` as an **Environment secret**;
- `GROQ_MODEL=qwen/qwen3.8-27b` and `GROQ_BASE_URL=https://api.groq.com/openai/v1` as Environment variables.

Normal CI jobs never receive provider secrets. Manual `workflow_dispatch` selects `groq` or `gemini`, a `smoke`, `tool-discipline`, or `representative` suite, `repetitions=1|2|3`, and `prompt_variant=v1|v2-strict`; only the selected provider job runs and receives its own secret. `tool-discipline` contains `find-01`, `create-01`, and `ambiguity-01` so stochastic function-calling reliability can be repeated without spending quota on the whole corpus. Artifact names include the prompt variant so baseline and variant reports remain distinct. `smoke` runs `find-01` + `move-01`; `representative` adds `create-01`, `ambiguity-01`, and `history-01`. Groq/Qwen live evaluation uses temperature 0.6, top_p 0.95, `max_completion_tokens=256`, `reasoning_effort=none`, and hidden reasoning. These settings are captured in run metadata. The smaller completion budget and instruct mode are deliberate: measured free-tier limits are 7000 input tokens/minute and 1000 output tokens/minute.

## Current scope

Stages 0–5 are implemented and Stage 6 live-provider validation is in progress: project bootstrap, domain persistence, deterministic search, bounded agent/tool layer, text-only web/evaluation MVP, replaceable OpenAI-compatible provider adapter, and controlled prompt/model experiments. Voice, Telegram, images, QR, MCP, PWA, and embeddings remain out of scope until live text-model evaluation produces evidence that they are worth adding.

## Stage 6 live evaluation

Real-model validation uses a deterministic fixture and a versioned corpus rather than the live inventory database.

The committed corpus is `eval/corpus-v1.json` (40 cases). Each case starts from `inventory-fixture-v1`, so prompt/model comparisons see the same initial categories, locations, items, ambiguity, aliases, and history. The harness creates a fresh temporary SQLite database per case and never points at the normal application database.

Canonical repeated commands are in `Justfile`:

- `just corpus-check` validates corpus/fixture compatibility and unique case IDs.
- `just live-eval` runs configured cases against the provider selected by `AH_THERE_IT_IS_LLM_*`; its optional repetitions argument reruns each selected case from a fresh fixture and records `trial` plus stable `execution_id` (for example `find-01#r2`).
- `just provider-smoke` remains the lightweight connectivity-only check.
- `just live-compare baseline.json variant.json comparison.json` creates a descriptive case-by-case comparison with exact provider-config fingerprints, rounds, checks, token usage, provider/client time, retry delay, tool usage/errors, and both assistant texts. It deliberately does not rank prompts or choose a winner.

`live-eval` intentionally refuses the offline heuristic provider unless `--allow-heuristic` is passed explicitly. The heuristic mode exists only to test harness plumbing; it is not a model-quality result.

The GitHub Actions manual provider jobs use the `live-llm-test` environment and run bounded smoke/representative suites before uploading JSON reports. Normal CI is green on Python 3.12/3.13. Live Gemini and Groq runs have confirmed complete `AgentRunner` tool loops. Groq diagnostics now record persistent-transport wall time, provider server time, attempts, and retry events; the latest smoke reduced `move-01` from 8 rounds to 3 after deterministic natural-phrase location fallback was added. The representative Groq subset subsequently exposed one create-path failure; after filtering single-token FTS noise, tightening create metadata rules, and accepting token-order-equivalent prior name searches, `create-01` completed in 3 rounds / 1.36 s with the item stored at the correct location and optional metadata left unknown/unset.
