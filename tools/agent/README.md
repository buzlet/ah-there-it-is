# Agent process tools

These helpers are optional process tooling, not application runtime features.

## Lifecycle checkpoints

`tools/agent/lifecycle_checkpoints.py`

Read-only Git/control/seed validation plus external lifecycle checkpoint state.

Manifest preflight accepts both legacy per-task manifests and current integrated-v8
manifests. Integrated manifests declare one shared implementation branch and must
align their ordered task IDs, exact spec paths, and seed destinations one-for-one.
The JSON result reports `manifest_format` and `manifest_mode`.

The manifest's required work directory is control metadata for the assigned host;
repository identity is checked from `--repo`/`--expected-repo-path`. This keeps the
same committed tests valid when CI checks out the repository at another absolute
path.

Current integrated batches use three explicit command surfaces:

```text
verify-batch-seed
batch-checkpoint
batch-checkpoint-status
```

Batch seed verification proves the control manifest and every ordered assignment
copy at the single seed commit. Batch checkpoints record preflight, seed, ordered
task heads/corrections, review, final-local verification, PR/exact head, exact-head
CI, and merge facts in an atomic private file outside the repository. Legacy
`verify-seed`, `checkpoint`, and `checkpoint-status` meanings are unchanged.

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
