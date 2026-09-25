# 0082 — benchmark aggregation and baseline/candidate comparison

Status: draft task spec; reconcile after 0061-0070.

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
