# Repeated development operations. `just` is the canonical task runner.

export PYTHONPATH := "src"

default:
    @just --list

test:
    python -m pytest

test-agent:
    python -m pytest tests/test_agent.py

test-web:
    python -m pytest tests/test_app.py tests/test_evaluation.py tests/test_experiments.py

test-provider:
    python -m pytest tests/test_provider.py

compile:
    python -m compileall -q src tests migrations

check: compile test

migrate:
    python -m alembic upgrade head

migration-check:
    rm -f /tmp/ah-there-it-is-migration-check.db
    AH_THERE_IT_IS_DATABASE_URL=sqlite:////tmp/ah-there-it-is-migration-check.db python -m alembic upgrade head
    AH_THERE_IT_IS_DATABASE_URL=sqlite:////tmp/ah-there-it-is-migration-check.db python -m alembic check
    rm -f /tmp/ah-there-it-is-migration-check.db

eval-export file="evaluation-cases.json":
    python -m ah_there_it_is.evaluation_export > "{{file}}"

experiment-replay name prompt version limit="50":
    python -m ah_there_it_is.experiment_replay --name "{{name}}" --prompt "{{prompt}}" --version "{{version}}" --limit "{{limit}}"

provider-smoke:
    python -m ah_there_it_is.provider_smoke

migration message:
    python -m alembic revision --autogenerate -m "{{message}}"

serve:
    python -m uvicorn ah_there_it_is.app:app --reload

corpus-check corpus="eval/corpus-v1.json":
    python -m ah_there_it_is.corpus_check "{{corpus}}"

live-eval corpus="eval/corpus-v1.json" limit="5" repetitions="1" output="live-eval.json":
    python -m ah_there_it_is.live_eval --corpus "{{corpus}}" --limit "{{limit}}" --repetitions "{{repetitions}}" --output "{{output}}"

live-compare baseline variant output="live-compare.json":
    python -m ah_there_it_is.live_compare "{{baseline}}" "{{variant}}" --output "{{output}}"
