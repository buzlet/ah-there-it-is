# Batch review: model evaluation 0081–0083

## Provenance

- Batch: `post-0070-model-evaluation-2026-09-25`
- Protocol: `agent-tasks/common/v8.md`
- Immutable control SHA: `f9ecf9ba5159a5dc0c16feaa1386f4cbd2c5a77d`
- Expected/start main: `153435ef3272a134d85ff02bcc370b8121b0708a`
- Sandbox source artifact: `sandbox-bundle-153435ef3272a134d85ff02bcc370b8121b0708a`
- Local synthetic baseline tag: `sandbox-base` (`a2522b1` locally; not an upstream GitHub SHA)
- Local batch seed: `2127410`
- Authoritative remote batch seed: `9b6f329cabf176f76a11c9d97f77eff1375b25f0`
- Implementation branch: `feat/model-evaluation-0081-0083`

The local synthetic history is execution evidence only. Remote GitHub commits below are the authoritative task ancestry.

## 0081 — benchmark campaign schema and repeated runner

Checkpoints:

- local implementation: `1db0d0a`
- remote implementation: `638ffee6f4ffd14d1e4e96c1af88ee70dec9e6ea`
- local cumulative-review correction: `3f4c50c`
- remote cumulative-review correction: `92e8e9ad50d682c0097d99d17b320bb1825ecf30`

Implemented a strict `benchmark-campaign-v1` manifest, deterministic repeated attempt slots, provider/config/prompt/corpus/probe identity binding, atomic replace-safe incremental JSON persistence, interruption-safe resume, secret redaction, and a fake-injectable execution boundary. A standalone manual runner composes existing live-eval/model-probe behavior without changing inventory semantics.

Focused verification before the initial checkpoint:

```text
.venv/bin/python -m pytest -q tests/test_benchmark_campaign.py tests/test_live_eval.py tests/test_model_probe.py -k "campaign or resume or manifest or provider or prompt or probe or secret"
make compile
git diff --check
```

Result: green (11 selected tests initially).

Cumulative self-review found one spec mismatch: `delay_seconds` separated campaign attempt slots but did not guarantee spacing between every underlying provider request inside a multi-round live case. The correction added a shared request throttle and an optional LLM-factory injection to the evaluation-only `live_eval.run_case` API; default `live_eval` behavior is unchanged. Normal tests remain fake-only and use no provider credentials.

Correction verification used the same exact focused command set and was green with 12 selected tests, followed by green `make compile` and `git diff --check`.

Correction count: 1.

## 0082 — benchmark aggregation and comparison

Checkpoints:

- local: `89da65e`
- remote: `49143a14cfecac2b5bf667d40882a5349c2ce966`

Implemented separate hard-correctness, behavior/repeatability, and operations aggregates with attempt-level evidence references. Provider/tool-contract, application checks, write-target safety, mutation correctness, quantity/lifecycle/Undo, and captured unsupported-fact failures remain explicit categories. Token/cost absence is `null`/unavailable rather than zero. Baseline/candidate output reports deltas and hard regressions without an overall score or automatic winner.

Focused verification:

```text
.venv/bin/python -m pytest -q tests/test_benchmark_comparison.py tests/test_benchmark_campaign.py tests/test_live_compare.py -k "benchmark or compare or aggregate or hard_gate or repeat or cost or latency"
make compile
git diff --check
```

Result: green (14 selected tests), compile and diff-check green.

Correction count: 0.

## 0083 — promotion hard-gate report

Checkpoints:

- local: `f512cf5`
- remote: `b615beaa2acae1ef644917ba4091bbb20bb22c2f`

Implemented report-only `promotion-report-v1` generation with baseline/candidate identity, exact evaluation versions, hard-gate reasons, behavioral/operational deltas, intermittent failures, known regressions/improvements, evidence-file references, and deterministic Markdown/JSON rendering. Evidence completeness is checked against exact declared attempt slots and fails closed. Cost/latency remain observations and never correctness gates. Promotion mode is explicitly manual; no runtime provider/model settings are modified.

Focused verification:

```text
.venv/bin/python -m pytest -q tests/test_promotion_report.py tests/test_benchmark_comparison.py tests/test_model_probe.py tests/test_evaluation.py tests/test_evaluation_export.py tests/test_scenario_eval.py tests/test_eval_checks.py -k "promotion or hard_gate or evaluation or report or scenario or probe"
make provider-contract
make compile
git diff --check
```

Result: green (38 selected tests); provider-contract green (23 tests); compile and diff-check green.

Correction count: 0.

## Cumulative self-review

Reviewed local `2127410..HEAD` and authoritative remote `9b6f329c..92e8e9ad` cumulatively. Remote comparison proves the implementation head is four commits ahead of the seed with the seed as merge base and zero commits behind.

Changed implementation surface is limited to evaluation campaign/comparison/promotion modules, evaluation documentation/example, focused tests, and the small optional evaluation-only `live_eval.run_case` LLM-factory injection required to enforce per-provider-request throttling. No inventory domain/service, DB model/migration, Web, Telegram/media, runtime CLI/config, pyproject, Makefile, AGENTS/HANDOFF, workflow, or product-design files changed. No dependency was added and no live provider was called.

No opaque overall score or automatic provider/model promotion is present. Raw attempt references remain available through aggregates/reports. Resume identity includes campaign, provider/model safe config, prompt, corpus, and probe bytes/versions. Durable writes preserve the last valid JSON across interruption.

Known pre-PR blocker: none.

## Final local verification

After the correction, ran the exact manifest final focused integration:

```text
.venv/bin/python -m pytest -q \
  tests/test_benchmark_campaign.py \
  tests/test_benchmark_comparison.py \
  tests/test_promotion_report.py \
  tests/test_live_eval.py \
  tests/test_live_compare.py \
  tests/test_model_probe.py \
  tests/test_evaluation.py \
  tests/test_evaluation_export.py \
  tests/test_scenario_eval.py \
  tests/test_eval_checks.py

make provider-contract
make compile
git diff --check
```

Result: 63 focused/integration tests green; provider-contract 23/23 green; compile and diff-check green. Worktree was clean before creating this review record.

`full_local_required: false`; repository-wide `make check`, migration/corpus/scenario/retrieval gates were intentionally not run locally. Exact-head application CI remains authoritative.
