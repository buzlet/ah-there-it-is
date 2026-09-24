# Assignment 0032: structured canonical verification runner

Protocol: `agent-tasks/common/v7.md`.

Branch: `feat/agent-canonical-verifier`

## Objective

Provide durable, structured supervision for the exact canonical verification set without changing what counts as canonical verification.

## Canonical commands

The helper must execute exactly these existing Just recipes in this order:

1. `just check`
2. `just migration-check`
3. `just corpus-check`
4. `just scenario-check`
5. `just scenario-eval`
6. `just retrieval-eval`
7. `just provider-contract`

Do not duplicate their underlying implementation in Python.

Do not add/remove/reorder checks.

## Tool

Add a stdlib-only helper under `tools/agent/`.

Inputs:

- repository path;
- external run-state/log directory;
- optional per-command timeout with a conservative default.

## Behavior

For every check:

- execute non-interactively from the supplied repository;
- preserve stdout/stderr in bounded/durable log files outside the worktree;
- record start/end/duration/exit code;
- record the Git HEAD under test;
- stop on first failed/timed-out canonical check;
- produce an atomic JSON summary.

Timeout termination must be process-group aware.

The default timeout must be long enough for normal project verification and must not be used as a performance assertion.

## Resume after controller disconnect

Support resuming the **verification supervisor state**, not blindly skipping tests.

If an earlier runner process is still alive, status inspection must identify that fact rather than launch a second verifier.

If a verifier process stopped between checks, a resume may continue only when:

- recorded Git HEAD exactly equals current HEAD;
- previously completed checks succeeded;
- command definitions still match the fixed canonical set.

If code HEAD changed, previous results cannot be reused for final verification.

After any implementation correction, final delivery still requires the complete canonical set on the final HEAD.

## Just surface

An optional thin Just recipe may invoke the helper, but the seven recipes above remain the canonical source of truth.

Do not change CI to use the helper in this assignment.

## Tests

Use fake `just` processes/commands where appropriate.

Cover:

- exact command order;
- stdout/stderr/log metadata;
- success;
- failure stops following checks;
- timeout and process cleanup;
- HEAD mismatch prevents resume;
- valid same-HEAD continuation;
- concurrent duplicate verifier refusal;
- state stored outside worktree.

## Constraints

No application assertions weakened, no canonical-set change, no CI workflow change, no third-party dependency.

## Verification

Focused helper tests plus the actual complete canonical set.
