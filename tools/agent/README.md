# Agent process tools

These helpers are optional process tooling, not application runtime features.

## Lifecycle checkpoints

`tools/agent/lifecycle_checkpoints.py`

Read-only Git/control/seed validation plus external lifecycle checkpoint state.

## Full-local verifier

`tools/agent/canonical_verifier.py`

Durably supervises the optional full-local integration sequence:

```text
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
```

Use it only when the active batch manifest sets `full_local_required: true`.

Do not run it after every task.

`just provider-contract` is a focused recipe, not part of universal full-local verification, because those tests already run inside full pytest.

## Bounded CI waiter

`tools/agent/ci_waiter.py`

Read-only exact-PR-head GitHub check observer with bounded registration, polling and overall timeouts. It never reruns, cancels or merges workflows.

## Execution model

The direct U24 execution environment is already connected to the machine. These tools do not create SSH sessions and do not launch or supervise nested Codex processes.
