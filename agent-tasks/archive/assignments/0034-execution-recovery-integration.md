# Assignment 0034: execution recovery integration and pilot hardening

Protocol: `agent-tasks/common/v7.md`.

Branch: `feat/agent-execution-recovery-integration`

## Objective

Integrate the execution helpers from 0030–0033 into one documented recovery workflow and prove that common disconnect/hang scenarios do not cause duplicate implementation processes or false lifecycle claims.

This is still process/development tooling, not inventory product work.

## Integration contract

Document and test the preferred v7 `u24-bash + ssh-codex` control flow:

1. v7 SSH/Codex preflight;
2. exact control/assignment prompt materialization outside worktree;
3. lifecycle preflight;
4. durable Codex start;
5. bounded trace/status observation;
6. lifecycle checkpoints;
7. structured canonical verifier where appropriate;
8. bounded CI waiter;
9. final durable Git/PR/merge verification.

Raw protocol fallbacks remain possible, but the helper path should be the recommended reliable path after this assignment.

## Controller recovery matrix

Add a concise deterministic recovery matrix covering at least:

- SSH disconnect while Codex still runs;
- controller restart while Codex still runs;
- Codex exits nonzero before seed;
- Codex exits nonzero after implementation commit but before PR;
- verifier still running after SSH disconnect;
- CI waiter timeout while GitHub checks remain queued;
- PR head changed by the same assignment correction;
- unexpected external main advance;
- stale PID metadata after process exit;
- completed merge but controller missed the final Codex output.

For each case identify the durable authorities to inspect and whether to:

- keep observing;
- resume an existing lifecycle;
- launch a new Codex process with a narrowly scoped continuation prompt;
- stop/report blocker.

Never authorize two concurrent Codex implementation processes on the same assignment branch.

## Continuation prompt rules

Define when a new Codex process may be launched after the original has definitively exited.

A continuation prompt must:

- identify the same immutable assignment/control SHA;
- state the durable branch/HEAD/PR state already reached;
- instruct Codex to continue, not recreate/reseed/rebase;
- preserve existing review/PR;
- rerun required verification after corrections;
- never reinterpret task scope.

Do not use `resume --last` without an exact known session identity and durable-state consistency.

## Integration tests

Use fake Codex/gh processes and temporary Git repositories.

Prove:

- duplicate run prevention across reconnect;
- status after simulated controller death;
- continuation only after original termination;
- lifecycle phase never regresses falsely;
- final merge can be recognized from Git durable state even if final JSONL output was missed;
- helper logs/state remain outside repository;
- no secrets are copied.

## Documentation

Add a focused operator document for controlling Codex over SSH from chat.

Include launcher fields but no real hostnames, usernames, tokens, private key paths or account details.

Update project process status factually: SSH-Codex execution tooling is prepared and exercised with deterministic fake-process integration; real batch execution itself is the operational channel pilot if this batch was launched through `ssh-codex`.

If this batch uses `remote-commander`, do not claim a real SSH-Codex pilot succeeded.

## Self-review

Audit the complete tooling surface for:

- unbounded waits;
- duplicate-process races;
- worktree writes in state/log helpers;
- token/environment dumps;
- shell injection of prompts;
- accidental application/runtime coupling.

## Constraints

No application/domain/search/provider behavior change, no Windows SSH-Codex, no new dependency, no product decision.

## Verification

Focused integration/tooling tests, then the complete canonical verification set.
