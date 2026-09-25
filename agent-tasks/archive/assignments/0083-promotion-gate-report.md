# 0083 — promotion hard-gate report and evaluation integration

Status: issued implementation spec for sandbox batch 0081–0083.

## Objective

Turn existing model probes/live corpus plus 0081-0082 campaign evidence into a reproducible promotion report while keeping the actual production/default model selection manual.

## Promotion report

Include:

- baseline identity/config;
- candidate identity/config;
- exact prompt/corpus/probe versions;
- hard-gate status and reasons;
- behavioral/operational comparison;
- intermittent failures;
- known regressions;
- known improvements;
- evidence file references;
- generation timestamp.

The report may say `hard_gate_passed: true|false`.

It must not edit application configuration, environment files or provider settings automatically.

## Hard gates

At minimum, promotion cannot pass when evidence shows:

- provider adapter/tool contract failure;
- required application scenario failure;
- write-target safety regression;
- mutation correctness regression;
- quantity/removed/Undo invariant regression;
- evaluation evidence incomplete relative to the declared campaign.

Do not turn cost/latency into correctness gates.

## Integration

- keep outputs under a versioned evaluation-results location;
- add documentation for running baseline/candidate campaigns manually;
- add deterministic fixture tests;
- expose a standalone command/module entry point if useful, but avoid touching the main runtime CLI if that would create conflict with 0071-0080.

No auto-promotion.


## Issued implementation constraints

Recommended source/test surface:
- src/ah_there_it_is/promotion_report.py
- tests/test_promotion_report.py
- concise evaluation usage documentation/example files under eval/

Expose a standalone module/command entry point such as
`python -m ah_there_it_is.promotion_report`.

Do not modify the main installed runtime CLI, Makefile, AGENTS.md, HANDOFF.md,
pyproject dependencies, application settings or CI workflows in this sibling
batch.

Promotion is report-only. Never modify provider/model configuration automatically.

The report must fail closed when required campaign evidence is incomplete.

## Focused verification

Run exactly:

    .venv/bin/python -m pytest -q tests/test_promotion_report.py tests/test_benchmark_comparison.py tests/test_model_probe.py tests/test_evaluation.py tests/test_evaluation_export.py tests/test_scenario_eval.py tests/test_eval_checks.py -k "promotion or hard_gate or evaluation or report or scenario or probe"
    make provider-contract
    make compile
    git diff --check
