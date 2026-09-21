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

The LLM is not a database client. Domain services own validation, identity, history, and mutations. The agent can mutate only stable IDs that the backend has resolved from prior tool results.

## Sandbox development

The project is kept compatible with packages already present in the OpenAI sandbox; no network dependency is introduced merely for development.

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
just compile
just check
just migrate
just migration-check
just serve
just eval-export evaluation-cases.json
```

If `just` is unavailable in a constrained sandbox, execute the exact underlying recipe command rather than adding a network dependency to install it.

## Offline web MVP

Stage 4 defaults to the deliberately tiny `HeuristicLLMClient`, so the whole browser -> agent -> tools -> SQLite path can be exercised without an external API. It understands only the small smoke subset documented in the agent code and must not be mistaken for production NLP.

Run migrations before starting the app:

```bash
just migrate
just serve
```

The web UI provides chat, inventory/item views, location/category views, manual item corrections, and evaluation views.

## Prompt/model evaluation

Every agent run stores:

- prompt version and exact SHA-256 prompt hash
- full system prompt
- provider/model/config metadata
- initial message context
- per-round tool calls and returned results
- completion/failure status and final response
- optional human rating from 1 to 5 plus a comment

An alternate prompt can be loaded from a file with `AH_THERE_IT_IS_PROMPT_FILE`; set `AH_THERE_IT_IS_PROMPT_VERSION` to a meaningful experiment label. Rated runs can be exported with `just eval-export` for later replay/experiment tooling.

The captured trace is evidence, not a full historical database snapshot. Exact historical-state replay is therefore not claimed; Stage 5 will make replay divergence explicit.

## Current scope

Stages 0–4 are complete: project bootstrap, domain persistence, deterministic search, bounded agent/tool layer, and the first text-only web/evaluation MVP. Stage 5 connects a real LLM provider and adds controlled prompt/model experiments over the accumulated evaluation corpus.
