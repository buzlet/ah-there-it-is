# Assignment 0031: lifecycle preflight and durable checkpoints

Protocol: `agent-tasks/common/v7.md`.

Branch: `feat/agent-lifecycle-checkpoints`

## Objective

Make assignment/batch prerequisite and progress state mechanically inspectable so the controller can recover from a disconnected or interrupted execution without guessing where the lifecycle stopped.

## Tooling

Add a stdlib-only helper under `tools/agent/`.

Keep it outside application runtime entry points.

## Read-only preflight

Provide machine-readable checks for a batch/assignment start covering the v7 invariants that are objective and locally inspectable.

At minimum support checking:

- repository identity/path;
- clean worktree;
- current branch;
- current `main` vs `origin/main`;
- expected start-main SHA when supplied;
- control branch exists locally/remotely after caller fetch;
- control branch points to the supplied control SHA;
- manifest and task spec exist at that exact control SHA;
- exact task ordering/branch/destination fields can be read;
- no target task branch already exists when creating a just-in-time seed unless the issued lifecycle explicitly expects it.

The helper must not rewrite history, create branches, merge, push or modify application files.

Network fetch remains an explicit controller/agent action; the checker operates on the fetched local Git state.

## Seed verification

Support a post-seed read-only check that verifies:

- task branch name;
- clean worktree;
- seed is HEAD;
- exactly one seed commit above the expected base main;
- seed parent equals supplied base/main SHA;
- assignment bytes in the branch match the exact source bytes at control SHA;
- seed remains an ancestor when later requested.

## Durable checkpoints

Add a checkpoint state format stored outside the repository.

A run/assignment checkpoint records monotonically advancing phases such as:

- `preflight_ok`
- `seeded`
- `implementation_ready`
- `focused_green`
- `canonical_green`
- `review_written`
- `pr_open`
- `ci_green`
- `merged`

Use a stable finite vocabulary.

Each checkpoint records:

- assignment;
- branch;
- current HEAD;
- phase;
- timestamp;
- optional PR number/head SHA/merge SHA fields appropriate to the phase.

Writes must be atomic.

Reject phase regression unless an explicit new correction iteration is represented without claiming an earlier phase disappeared.

## Recovery semantics

The helper never decides that implementation should be rerun.

Its status output gives the controller durable facts. Repository/PR state remains authoritative.

After connection loss a controller can compare:

- Codex runner state from Assignment 0030;
- lifecycle checkpoint;
- Git durable state;

before deciding what to do.

## Tests

Use temporary local Git repositories.

Cover:

- correct/wrong start SHA;
- dirty worktree;
- wrong control SHA;
- assignment byte mismatch;
- valid/invalid seed ancestry;
- monotonic checkpoints;
- correction iteration representation;
- atomic state;
- malformed/stale checkpoint detection.

## Constraints

No GitHub network/API helper yet, no branch mutation, no application behavior, no new dependency.

## Verification

Focused tooling tests, then full canonical verification.
