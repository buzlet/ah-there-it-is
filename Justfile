# Repeated development operations. `just` is the canonical task runner.

export PYTHONPATH := "src"

default:
    @just --list

test:
    python -m pytest

compile:
    python -m compileall -q src tests migrations

check: compile test

migrate:
    python -m alembic upgrade head

migration message:
    python -m alembic revision --autogenerate -m "{{message}}"

serve:
    python -m uvicorn ah_there_it_is.app:app --reload
