# 0082 — benchmark aggregation and baseline/candidate comparison

Status: issued implementation spec for sandbox batch 0081–0083.

## Objective

Aggregate campaign attempts and compare a candidate against a baseline without hiding failures inside one opaque score.

## Aggregation

Report separately:

Hard correctness:
- provider/tool-contract pass/fail;
- application check failures;
- write-target safety failures;
- hallucination/unsupported-fact failures where captured by corpus checks;
- quantity/lifecycle/Undo semantic failures represented in the post-0070 corpus.

Behavior:
- completed/passed attempts;
- clarification counts where trace data permits;
- rounds/tool calls;
- repeated-run disagreement/intermittent failure rate.

Operations:
- wall time;
- provider errors/rate limits;
- token/cost fields only when available and clearly marked unavailable otherwise.

## Comparison

Produce baseline-vs-candidate deltas without declaring a winner automatically.

A candidate with a hard correctness regression is marked as failing the hard gate regardless of latency/cost improvements.

Keep raw attempt references so every aggregate can be traced back.

## Report format

Create a versioned machine-readable comparison JSON plus concise Markdown rendering.

Tests use fixture campaign results only; no live provider.


## Issued implementation constraints

Create a comparison/aggregation layer separate from campaign execution.

Recommended source/test surface:
- src/ah_there_it_is/benchmark_compare.py
- tests/test_benchmark_comparison.py

Do not create one composite intelligence score.

Hard correctness, behavioral observations and operational observations remain
separate fields.

Every aggregate must retain references back to campaign/attempt evidence.

Unavailable token/cost data is represented explicitly as unavailable/null, not
zero.

A hard correctness regression makes the hard gate fail regardless of cost/latency.

## Focused verification

Run exactly:

    .venv/bin/python -m pytest -q tests/test_benchmark_comparison.py tests/test_benchmark_campaign.py tests/test_live_compare.py -k "benchmark or compare or aggregate or hard_gate or repeat or cost or latency"
    make compile
    git diff --check
