# Ah, There It Is!

Local-first inventory memory for finding physical things using natural-language messages.

## MVP architecture

- FastAPI web application
- SQLAlchemy 2 + SQLite persistence
- Alembic migrations
- deterministic exact/normalized/FTS5 candidate search
- provider-neutral bounded LLM tool loop
- Pydantic tool schemas
- Jinja2/HTMX-oriented web UI

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
just compile
just check
just migrate
just migration-check
just serve
```

If `just` is unavailable in a constrained sandbox, execute the exact underlying recipe command rather than adding a network dependency to install it.

## Offline agent development

`ScriptedLLMClient` drives deterministic tool-loop tests. `HeuristicLLMClient` can smoke-test only a deliberately small subset (`Где X?`, `Положил/переложил X в Y`) without any external model. It is not intended to replace a real LLM provider.

## Current scope

Stages 0–3 are complete: project bootstrap, inventory/domain persistence, deterministic search, and the bounded provider-neutral agent/tool layer. Stage 4 connects that core to the first usable text-only web chat and read-only inventory views.
