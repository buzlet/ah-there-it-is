# Agent process tools

These helpers are optional process tooling, not application runtime features.

## Active v9 model

v9 relies on Git/PR history instead of a separate lifecycle state machine.

Normal v9 work does not use:

- control SHA/branch;
- seed;
- assignment copies;
- lifecycle checkpoint journal;
- checkpoint-SHA registry.

## Full-local verifier

`tools/agent/canonical_verifier.py`

Optional when the issued batch sets `full_local_required: true` and durable
supervision of the declared full-local sequence is useful.

Do not run it after every task.

## Bounded CI waiter

`tools/agent/ci_waiter.py`

Optional read-only exact-PR-head observer where GitHub CLI access is available.
It never reruns, cancels or merges workflows.

Sandbox normally uses the GitHub connector instead of shell GitHub access.

## Legacy v8 helpers

`tools/agent/lifecycle_checkpoints.py` and `tools/agent/process_state.py` are
retained for historical v8 provenance and verification. No active v8 batch remains at v9 adoption.

Do not introduce their seed/control/checkpoint model into new v9 batches.
