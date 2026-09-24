# Assignment 0060: integrated-batch seed and checkpoint lifecycle

## Objective

Make lifecycle verification/checkpoint state represent v8's one-seed/ordered-checkpoints/one-review/one-PR lifecycle instead of only the historical one-assignment model.

Build on the integrated manifest parser from 0059.

## Batch seed verification

Add a batch-mode seed verifier that proves:

- implementation branch is the manifest's one branch;
- seed is based on the exact expected start-main;
- active manifest bytes match the immutable control manifest;
- every task spec at the immutable control SHA is copied byte-for-byte to its declared assignment destination;
- the seed contains the complete declared batch material;
- task specs are not omitted/reordered/substituted;
- the seed remains an ancestor when verification is performed at a later implementation head.

Do not amend/rewrite seeds. Verification is read-only.

Legacy single-assignment seed verification may remain for historical tooling compatibility.

## Batch checkpoint state

Add a batch-oriented durable state mode outside the repository.

Represent at minimum:

- batch/control/start-main identity;
- preflight success;
- seed SHA;
- ordered task checkpoint heads and correction counts;
- cumulative review/final-local verification state;
- PR number and exact PR head;
- CI-green exact head;
- merge SHA.

Enforce:

- task checkpoints can only advance in manifest order;
- no skipped/duplicate task checkpoint;
- recorded heads are valid commits on the implementation branch and preserve seed ancestry;
- correction metadata cannot regress the high-water mark;
- PR/CI/merge facts are internally consistent;
- state writes remain atomic/private and the state directory remains outside the repository.

The committed review remains pre-PR as defined by v8. Post-merge completion facts belong to external checkpoint/completion state; do not rewrite the merged review to add them.

## CLI/tests/docs

- Add clear batch-mode CLI subcommands or flags without silently changing legacy command meaning.
- Machine-readable status must distinguish current/stale/invalid state.
- Extend `tests/test_lifecycle_checkpoints.py` for monotonic 10-task progression, skipped/out-of-order rejection, later-head ancestry, PR-head change, CI/merge consistency, malformed state and atomic-write failure.
- Update `tools/agent/README.md` with the v8 batch lifecycle surface.

## Constraints

Process tooling only. No application code, GitHub network mutation, CI workflow modification, dependency addition or execution-channel redesign.

## Focused verification

Use the manifest-declared 0060 check only.
