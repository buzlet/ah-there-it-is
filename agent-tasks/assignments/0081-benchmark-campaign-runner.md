# 0081 — benchmark campaign schema and repeated runner

Status: issued implementation spec for sandbox batch 0081–0083.

## Objective

Build a provider-neutral benchmark campaign layer that orchestrates the already-existing evaluation engines without duplicating their business logic.

## Inputs

Define a strict versioned campaign manifest able to specify:

- campaign id/version;
- candidate provider/model/config label;
- prompt version/file/hash expectation;
- selected live-eval corpus/case IDs;
- selected model-probe suite/case IDs;
- repetitions per nondeterministic live case;
- optional delay between provider calls;
- output directory/file prefix.

Do not put API keys in campaign files.

## Runner

Implement a coordinator that:

- invokes/reuses existing live_eval/model_probe APIs in-process where practical;
- executes repeated live cases deterministically in declared order;
- records each individual attempt, not only aggregates;
- writes incremental durable JSON so long/limited-quota runs retain completed work after interruption;
- records provider info, prompt hash/version, corpus/suite versions and timestamps;
- can resume an incomplete campaign without rerunning already completed identical attempt slots.

No normal CI test may require a real provider.

## Testing

Use fake clients/execution hooks to test:

- manifest validation;
- repeated-run ordering;
- resume;
- interrupted write recovery;
- provider/config identity mismatch;
- no secret persistence.

Do not change AgentRunner/inventory semantics.


## Issued implementation constraints

Create a new evaluation-focused module boundary; do not modify AgentRunner,
InventoryService, Web routes, migrations, Telegram/media modules or runtime config.

Recommended source surface:
- src/ah_there_it_is/benchmark_campaign.py
- tests/test_benchmark_campaign.py
- versioned example/schema material under eval/

Campaign identity must include enough immutable information to refuse an unsafe
resume after provider/model/prompt/corpus/probe/campaign configuration changes.

Incremental result persistence must use replace-safe writes so an interrupted
write cannot destroy the last valid completed-attempt state.

Do not persist API keys, authorization headers or provider secrets.

No real provider calls in tests or local sandbox verification.

## Focused verification

Run exactly:

    .venv/bin/python -m pytest -q tests/test_benchmark_campaign.py tests/test_live_eval.py tests/test_model_probe.py -k "campaign or resume or manifest or provider or prompt or probe or secret"
    make compile
    git diff --check
