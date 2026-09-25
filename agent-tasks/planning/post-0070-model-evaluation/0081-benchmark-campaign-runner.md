# 0081 — benchmark campaign schema and repeated runner

Status: draft task spec; reconcile after 0061-0070.

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
