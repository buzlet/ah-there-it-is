# Makefile
# Repeated development operations. GNU Make is the canonical task runner.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python)
SANDBOX_PYTHON ?= /opt/pyvenv/bin/python

FILE ?= evaluation-cases.json
NAME ?=
PROMPT ?=
VERSION ?=
LIMIT ?= 50
CORPUS ?= eval/corpus-v1.json
SCENARIOS ?= eval/scenarios-v1.json
RETRIEVAL_CORPUS ?= eval/retrieval-robustness-v1.json
SUITE ?= eval/model-probes-v1.json
MESSAGE ?=
BASELINE ?=
VARIANT ?=
DESTINATION ?=
DATABASE ?=
CANDIDATE ?=
SOURCE ?=

export PYTHONPATH := src

.PHONY: help test test-agent test-web test-provider compile check migrate migration-check \
	eval-export experiment-replay provider-smoke migration serve corpus-check live-eval \
	live-compare scenario-check scenario-eval retrieval-eval model-probe provider-contract \
	storage-test db-backup db-validate db-restore db-restore-rehearsal portable-export \
	portable-import portable-import-dry-run bootstrap-preflight bootstrap-apply \
	sandbox-preflight sandbox-bootstrap

help:
	@printf '%s\n' \
	  'make test' \
	  'make compile' \
	  'make check' \
	  'make migration-check' \
	  'make corpus-check' \
	  'make scenario-check' \
	  'make scenario-eval' \
	  'make retrieval-eval' \
	  'make provider-contract' \
	  'make sandbox-bootstrap'

test:
	$(PYTHON) -m pytest

test-agent:
	$(PYTHON) -m pytest tests/test_agent.py

test-web:
	$(PYTHON) -m pytest tests/test_app.py tests/test_evaluation.py tests/test_experiments.py

test-provider:
	$(PYTHON) -m pytest tests/test_provider.py

compile:
	$(PYTHON) -m compileall -q src tests

check: compile test

migrate:
	$(PYTHON) -m ah_there_it_is.storage_cli upgrade

migration-check:
	$(PYTHON) -m ah_there_it_is.verification_paths migration-check

eval-export:
	$(PYTHON) -m ah_there_it_is.evaluation_export > "$(FILE)"

experiment-replay:
	@test -n "$(NAME)" && test -n "$(PROMPT)" && test -n "$(VERSION)"
	$(PYTHON) -m ah_there_it_is.experiment_replay --name "$(NAME)" --prompt "$(PROMPT)" --version "$(VERSION)" --limit "$(LIMIT)"

provider-smoke:
	$(PYTHON) -m ah_there_it_is.provider_smoke

migration:
	@test -n "$(MESSAGE)"
	$(PYTHON) -m alembic revision --autogenerate -m "$(MESSAGE)"

serve:
	$(PYTHON) -m uvicorn ah_there_it_is.app:create_app --factory --reload --host 127.0.0.1 --port 8000

corpus-check:
	$(PYTHON) -m ah_there_it_is.corpus_check "$(CORPUS)"

live-eval: OUTPUT ?= live-eval.json
live-eval:
	$(PYTHON) -m ah_there_it_is.live_eval --corpus "$(CORPUS)" --limit "$(LIMIT)" --output "$(OUTPUT)"

live-compare: OUTPUT ?= live-compare.json
live-compare:
	@test -n "$(BASELINE)" && test -n "$(VARIANT)"
	$(PYTHON) -m ah_there_it_is.live_compare "$(BASELINE)" "$(VARIANT)" --output "$(OUTPUT)"

scenario-check:
	$(PYTHON) -c "from ah_there_it_is.agent.scenario_mock import load_scenario_suite; s=load_scenario_suite('$(SCENARIOS)'); print(f'{s.version}: {len(s.cases)} scenarios')"

scenario-eval:
	$(PYTHON) -m ah_there_it_is.scenario_eval --corpus "$(CORPUS)" --scenarios "$(SCENARIOS)"

retrieval-eval:
	$(PYTHON) -m ah_there_it_is.retrieval_eval --corpus "$(RETRIEVAL_CORPUS)"

model-probe: OUTPUT ?= model-probe.json
model-probe:
	$(PYTHON) -m ah_there_it_is.model_probe --suite "$(SUITE)" --output "$(OUTPUT)"

provider-contract:
	$(PYTHON) -m pytest tests/test_provider.py tests/test_model_probe.py

storage-test:
	$(PYTHON) -m pytest tests/test_storage.py

db-backup:
	@test -n "$(DESTINATION)"
	$(PYTHON) -m ah_there_it_is.storage_cli backup "$(DESTINATION)"

db-validate:
	@test -n "$(DATABASE)"
	$(PYTHON) -m ah_there_it_is.storage_cli validate "$(DATABASE)"

db-restore:
	@test -n "$(CANDIDATE)"
	$(PYTHON) -m ah_there_it_is.storage_cli restore "$(CANDIDATE)"

db-restore-rehearsal:
	@test -n "$(CANDIDATE)"
	$(PYTHON) -m ah_there_it_is.storage_cli restore-rehearsal "$(CANDIDATE)"

portable-export:
	@test -n "$(DESTINATION)"
	$(PYTHON) -m ah_there_it_is.storage_cli export-json "$(DESTINATION)"

portable-import:
	@test -n "$(SOURCE)" && test -n "$(DESTINATION)"
	$(PYTHON) -m ah_there_it_is.storage_cli import-json "$(SOURCE)" "$(DESTINATION)"

portable-import-dry-run:
	@test -n "$(SOURCE)" && test -n "$(DESTINATION)"
	$(PYTHON) -m ah_there_it_is.storage_cli import-json "$(SOURCE)" "$(DESTINATION)" --dry-run

bootstrap-preflight:
	@test -n "$(SOURCE)"
	$(PYTHON) -m ah_there_it_is.storage_cli bootstrap-preflight "$(SOURCE)"

bootstrap-apply:
	@test -n "$(SOURCE)"
	$(PYTHON) -m ah_there_it_is.storage_cli bootstrap-apply "$(SOURCE)"

sandbox-preflight:
	@command -v make >/dev/null
	@command -v git >/dev/null
	@command -v "$(SANDBOX_PYTHON)" >/dev/null
	@test "$$("$(SANDBOX_PYTHON)" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" = "3.13"
	@test -f ".sandbox/MANIFEST.txt"
	@"$(SANDBOX_PYTHON)" -c 'import importlib.util; required=("setuptools.build_meta","fastapi","pydantic","sqlalchemy","alembic","jinja2","httpx","uvicorn","pytest","packaging"); missing=[name for name in required if importlib.util.find_spec(name) is None]; assert not missing, f"missing sandbox packages: {missing}"'

sandbox-bootstrap: sandbox-preflight
	@if [ ! -d .git ]; then \
	  source_sha="$$(sed -n 's/^source_commit=//p' .sandbox/MANIFEST.txt)"; \
	  test -n "$${source_sha}"; \
	  git init -q --initial-branch=sandbox-work; \
	  git config user.name sandbox-bundle; \
	  git config user.email sandbox-bundle@invalid; \
	  printf '.sandbox/\n.venv/\n' >> .git/info/exclude; \
	  git add -A; \
	  git commit -q -m "sandbox baseline for $${source_sha}"; \
	  git tag sandbox-base; \
	fi
	@test "$$(git tag --list sandbox-base)" = "sandbox-base"
	@test -z "$$(git status --porcelain)"
	rm -rf .venv
	"$(SANDBOX_PYTHON)" -m venv .venv
	@parent_site="$$("$(SANDBOX_PYTHON)" -c 'import site; print(site.getsitepackages()[0])')"; \
	 child_site="$$(.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')"; \
	 printf '%s\n' "$${parent_site}" > "$${child_site}/chatgpt-sandbox-parent.pth"
	PIP_NO_INDEX=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
	  .venv/bin/python -m pip install --no-index --no-build-isolation --no-deps .
	.venv/bin/python tools/sandbox/check_requirements.py
	@.venv/bin/python -c 'import sys; print("sandbox environment ready:", sys.version)'
