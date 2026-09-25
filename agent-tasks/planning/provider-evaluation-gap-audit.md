# Provider/model evaluation gap audit

Status: temporary draft for post-0061-0070 reconciliation. Not implementation authority.

## Existing capabilities

The repository already has several distinct evaluation layers:

- `scenario_eval.py` + `eval/scenarios-v1.json`: deterministic/provider-neutral application behavior using model doubles;
- `live_eval.py` + `eval/corpus-v1.json`: real configured provider against application-level corpus;
- `model_probe.py` + `eval/model-probes-v1.json`: provider/adapter contract testing without inventory business logic;
- `retrieval_eval.py`: deterministic retrieval evaluation;
- prompt experiment/replay modules and persisted experiment/evaluation logs;
- evaluation export and browser views;
- captured provider metadata, prompt hashes/versioning and tool traces.

This is already enough infrastructure to avoid making application development depend on one particular model.

## Missing unifying contract

The major gap is not another evaluator. It is a **promotion protocol** answering:

> Given model/provider/configuration A and B, what evidence is required before changing the application's configured production/default model?

The promotion layer should consume existing evidence rather than duplicate scenario/live/probe engines.

## Proposed evaluation dimensions

### Hard correctness gates

A candidate must not regress:

- tool schema/adapter contract;
- write-target safety;
- mutation correctness;
- transaction/rollback behavior;
- quantity/lifecycle semantics;
- unsupported-fact hallucination checks;
- required clarification on true target ambiguity.

These are pass/fail gates, not weighted preferences.

### Behavioral quality metrics

Measure separately:

- scenario success rate;
- unnecessary clarification rate;
- failure to clarify target ambiguity;
- number of tool rounds/calls;
- unnecessary searches/retries;
- final-answer factual consistency with tool results;
- quantity uncertainty handling;
- correct use of remove/restore/Undo;
- Russian-language instruction adherence.

### Operational metrics

Record, but do not mix silently into correctness:

- wall latency;
- provider-reported or locally counted tokens where available;
- estimated/request cost where available;
- provider errors/rate limits;
- repeatability across repeated runs.

## Repetition

One live run is insufficient for nondeterministic models.

A benchmark campaign should support repeated runs per case/configuration and report:

- success count / total;
- distribution of rounds/tool calls;
- error classes;
- disagreement cases;
- stable failures vs intermittent failures.

Do not reduce repeated outcomes to a single opaque score.

## Promotion result

Prefer a structured result such as:

```text
candidate configuration
hard-gate status
scenario/live corpus results
repeatability
clarification metrics
latency/token/cost observations
known regressions
known improvements
prompt version/hash
corpus versions
timestamp
```

The subsystem may generate a recommendation report, but application runtime must consume only an explicitly selected configuration. Evaluation must never auto-promote a provider/model.

## Corpus policy

After 0061-0070, the main product corpus should be Russian-first.

Keep separate suites for:

1. deterministic mock/domain behavior;
2. provider adapter contract;
3. live application behavior;
4. retrieval.

Do not make live provider availability a requirement for normal CI.

## Reuse vs new code

Likely reusable without redesign:

- AgentRunLog/evaluation persistence;
- tool traces;
- prompt hash/version;
- live_eval case execution;
- scenario_eval deterministic checks;
- model_probe;
- experiment replay.

Likely additions after 0070:

- benchmark campaign manifest/config;
- repeated-run coordinator;
- normalized aggregation/reporting;
- baseline-vs-candidate comparison;
- explicit hard-gate result;
- durable report format under `eval/results/`.

## Things not to do

- no provider-specific business logic in InventoryService/AgentRunner;
- no single composite "intelligence score" that hides hard failures;
- no production auto-promotion;
- no live-provider calls in ordinary unit tests;
- no model-specific workaround added before it appears as a measured scenario failure;
- no multilingual benchmark expansion under the current Russian-only product scope.

## Post-0070 task candidate

Create one focused evaluation batch after the final core correctness audit, not before.

It should begin by re-auditing the actual 0070 evaluation changes, because assignment 0068 may already implement part of the behavior described here.
