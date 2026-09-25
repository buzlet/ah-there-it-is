# 0083 — promotion hard-gate report and evaluation integration

Status: draft task spec; reconcile after 0061-0070.

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
