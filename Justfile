# Repeated development operations. `just` is the canonical task runner.

export PYTHONPATH := "src"

default:
    @just --list

test:
    python -m pytest

test-agent:
    python -m pytest tests/test_agent.py

test-web:
    python -m pytest tests/test_app.py tests/test_evaluation.py

compile:
    python -m compileall -q src tests migrations

check: compile test

migrate:
    python -m alembic upgrade head

migration-check:
    python -m alembic check

eval-export file="evaluation-cases.json":
    python -m ah_there_it_is.evaluation_export > "{{file}}"

migration message:
    python -m alembic revision --autogenerate -m "{{message}}"

serve:
    python -m uvicorn ah_there_it_is.app:app --reload
