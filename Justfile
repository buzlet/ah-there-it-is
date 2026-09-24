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
    python -m compileall -q src tests

check: compile test

migrate:
    python -m ah_there_it_is.storage_cli upgrade

migration-check:
    rm -f /tmp/ah-there-it-is-migration-check.db
    AH_THERE_IT_IS_DATABASE_URL=sqlite:////tmp/ah-there-it-is-migration-check.db python -m ah_there_it_is.storage_cli upgrade
    AH_THERE_IT_IS_DATABASE_URL=sqlite:////tmp/ah-there-it-is-migration-check.db python -m ah_there_it_is.storage_cli migration-check
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
    python -m uvicorn ah_there_it_is.app:create_app --factory --reload --host 127.0.0.1 --port 8000

corpus-check corpus="eval/corpus-v1.json":
    python -m ah_there_it_is.corpus_check "{{corpus}}"

live-eval corpus="eval/corpus-v1.json" limit="5" output="live-eval.json":
    python -m ah_there_it_is.live_eval --corpus "{{corpus}}" --limit "{{limit}}" --output "{{output}}"

live-compare baseline variant output="live-compare.json":
    python -m ah_there_it_is.live_compare "{{baseline}}" "{{variant}}" --output "{{output}}"

scenario-check scenarios="eval/scenarios-v1.json":
    python -c "from ah_there_it_is.agent.scenario_mock import load_scenario_suite; s=load_scenario_suite('{{scenarios}}'); print(f'{s.version}: {len(s.cases)} scenarios')"

scenario-eval corpus="eval/corpus-v1.json" scenarios="eval/scenarios-v1.json" output="scenario-eval.json":
    python -m ah_there_it_is.scenario_eval --corpus "{{corpus}}" --scenarios "{{scenarios}}" --output "{{output}}"

retrieval-eval corpus="eval/retrieval-robustness-v1.json" output="/tmp/ah-there-it-is-retrieval-eval.json":
    python -m ah_there_it_is.retrieval_eval --corpus "{{corpus}}" --output "{{output}}"

model-probe suite="eval/model-probes-v1.json" output="model-probe.json":
    python -m ah_there_it_is.model_probe --suite "{{suite}}" --output "{{output}}"

provider-contract:
    python -m pytest tests/test_provider.py tests/test_model_probe.py

storage-test:
    python -m pytest tests/test_storage.py

db-backup destination="ah-there-it-is.backup.db":
    python -m ah_there_it_is.storage_cli backup "{{destination}}"

db-validate database:
    python -m ah_there_it_is.storage_cli validate "{{database}}"

db-restore candidate:
    python -m ah_there_it_is.storage_cli restore "{{candidate}}"

db-restore-rehearsal candidate:
    python -m ah_there_it_is.storage_cli restore-rehearsal "{{candidate}}"

portable-export destination="inventory-export.json":
    python -m ah_there_it_is.storage_cli export-json "{{destination}}"


portable-import source destination:
    python -m ah_there_it_is.storage_cli import-json "{{source}}" "{{destination}}"

portable-import-dry-run source destination:
    python -m ah_there_it_is.storage_cli import-json "{{source}}" "{{destination}}" --dry-run

bootstrap-preflight source:
    python -m ah_there_it_is.storage_cli bootstrap-preflight "{{source}}"

bootstrap-apply source:
    python -m ah_there_it_is.storage_cli bootstrap-apply "{{source}}"
