# Assignment 0033: bounded GitHub CI waiter

Protocol: `agent-tasks/common/v7.md`.

Branch: `feat/agent-bounded-ci-waiter`

## Objective

Replace opaque/unbounded PR check waiting with a deterministic helper that observes the exact PR head, has a finite timeout, and never triggers duplicate CI.

## Dependency boundary

Use the existing authenticated GitHub CLI (`gh`) as an external operator tool.

Do not add a Python GitHub SDK or runtime dependency.

Do not read/store GitHub tokens directly.

## Tool

Add a stdlib-only helper under `tools/agent/`.

Inputs include:

- repository `owner/name`;
- PR number;
- expected PR head SHA;
- timeout (default 30 minutes);
- bounded polling interval;
- optional external state/log directory.

## Head safety

Before and during waiting, verify the PR still points to the expected head SHA.

If the PR head changes unexpectedly:

- stop;
- return a distinct non-success result;
- do not continue observing the wrong head;
- do not merge.

## Check observation

Use `gh api` / equivalent non-interactive GitHub CLI calls to inspect checks for the expected commit.

Do not use an unbounded interactive `gh ... --watch`.

Distinguish:

- checks not yet registered;
- queued/in progress;
- successful/neutral/skipped terminal checks;
- failed/cancelled/timed-out/action-required terminal checks;
- timeout waiting.

A normal implementation PR must not be treated as green merely because zero checks are currently visible immediately after PR creation. Allow a bounded registration grace period.

## Output

Emit concise machine-readable JSON with:

- PR;
- expected/current head;
- observed checks;
- elapsed time;
- final state;
- failure reason when non-success.

Store no credentials.

## Side-effect policy

The helper is observation-only.

It must never:

- rerun a workflow;
- cancel a workflow;
- merge a PR;
- push;
- modify a branch.

CI corrections and merge remain owned by the implementation agent under v7.

## Tests

Mock the `gh` subprocess boundary.

Cover:

- delayed check registration;
- queued -> success;
- immediate failure;
- head changes;
- mixed successful/skipped checks;
- timeout;
- malformed GitHub response;
- missing/unauthenticated gh failure;
- no duplicate/rerun commands emitted.

## Documentation

Update execution-channel tooling docs to show the bounded waiter as the preferred v7 CI observation path once available.

## Constraints

No workflow change, no GitHub Actions matrix change, no application code change, no dependency.

## Verification

Focused tooling tests then full canonical verification.
