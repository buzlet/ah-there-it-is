# Ah, There It Is!

Local-first inventory memory for finding physical things using natural-language messages.

## MVP architecture

- FastAPI web application
- SQLAlchemy + SQLite persistence (added in Stage 1)
- Pydantic schemas
- Jinja2/HTMX-oriented web UI
- Small in-process LLM tool loop (added later)

The LLM is not a database client. Domain services own all validation, identity, history, and mutations.

## Sandbox development

Stage 0 is intentionally compatible with the packages already present in the OpenAI sandbox. No network access is required.

Verified environment while bootstrapping:

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

## Run

From the repository root:

```bash
PYTHONPATH=src uvicorn ah_there_it_is.app:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/`.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Test

```bash
PYTHONPATH=src pytest
```

## Current scope

Stage 0 contains only the project skeleton, application configuration, health endpoint, initial web shell, and smoke tests. Database/domain behavior begins in Stage 1.
