# SSH-Codex controller workflow

This is the recommended recovery workflow for the v7 `u24-bash + ssh-codex`
pair. It coordinates the existing lifecycle preflight, durable session runner,
checkpoints, canonical verifier, and bounded CI waiter. It is process tooling;
it does not change application behavior.

## Launcher and preflight

Supply explicit launcher fields for each assignment:

```text
host_profile: u24-bash
execution_channel: ssh-codex
ssh_target: <SSH config alias or user@host>
repo_path: <absolute U24 repository worktree path>
codex_bin: codex
```

The selected host/channel pair stays fixed through merge. Reconnect using the
same SSH target and repository path. Before launching Codex, follow protocol
v7: confirm non-interactive SSH access, repository identity, `.venv` Python,
`git`, `just`, Codex version and local login status, then run the assignment's
read-only lifecycle preflight. On the selected U24 host, the checks are:

```bash
cd "$repo_path"
export PATH="$PWD/.venv/bin:$PATH"
python -c 'import os, sys; print(sys.executable); print(os.name)'
git status --short --branch
git remote get-url origin
just --version
"$codex_bin" --version
"$codex_bin" login status
```

The Python executable must resolve inside this worktree's `.venv/bin` and
`os.name` must be `posix`. Do not initiate login or inspect authentication
files. A login-status result does not prove a live Codex request will work; on
request authentication failure, stop and report it.

Keep the external state root stable across controller restarts and reconnects.
Prompts, lock records, logs, canonical-verifier runs, CI observations, and
checkpoints belong under this root, outside the Git worktree and outside `/tmp`.

## Assignment flow

1. Fetch the control branch and `origin/main`, then run
   `lifecycle_checkpoints.py preflight` with the immutable control SHA, expected
   start-main SHA, task order, branch, and repository identity.
2. Materialize one immutable prompt from the task blob at the control SHA. The
   helper includes the exact task bytes and a channel header, writes the prompt
   and a hash-only metadata sidecar outside the worktree, and refuses to
   overwrite either file:

   ```bash
   python tools/agent/execution_recovery.py materialize \
     --repo <repo_path> \
     --control-sha <immutable-control-sha> \
     --manifest <manifest-path-at-control-sha> \
     --task <four-digit-task-id> \
     --task-order <comma-separated-task-order> \
     --start-main-sha <expected-origin-main-sha> \
     --output <external-state-root>/prompts/<task>-attempt-1.md
   ```

3. Create the one seed commit from those exact assignment bytes. Run
   `lifecycle_checkpoints.py verify-seed` and record the `seeded` checkpoint.
   The recovery helper does not replace lifecycle preflight or seed verification.
4. Start Codex with a new run ID and the materialized prompt. The helper uses a
   kernel-held lock keyed by the Git common directory and assignment branch;
   the detached supervisor keeps that lock while it runs. Use the same state
   root for every controller invocation:

   ```bash
   python tools/agent/execution_recovery.py start \
     --repo <repo_path> \
     --branch <assignment-branch> \
     --run-id <fresh-immutable-run-id> \
     --prompt-file <external-state-root>/prompts/<task>-attempt-1.md \
     --state-dir <external-state-root> \
     --control-sha <immutable-control-sha> \
     --task <four-digit-task-id> \
     --codex-bin <codex-command>
   ```

5. On reconnect or controller restart, inspect the branch lifecycle before
   doing anything else:

   ```bash
   python tools/agent/execution_recovery.py status \
     --repo <repo_path> --branch <assignment-branch> \
     --state-dir <external-state-root>

   python tools/agent/codex_session.py tail \
     --run-id <run-id> \
     --state-dir <external-state-root>/codex-runs \
     --stream stdout --max-bytes 16384 --max-lines 100
   ```

   A held branch lock or a live/orphaned process group means keep observing.
   Do not launch direct `codex exec` or another helper run while one is active.
   Tail reads are bounded. JSONL, stderr, terminal result, and owner state stay
   outside the worktree.
6. Advance lifecycle checkpoints only from durable facts. Checkpoint writes are
   monotonic; an explicit correction iteration is required to record a
   regression. Recovery `status` is read-only and never changes checkpoint
   phase.
7. After implementation commits, run focused checks and the fixed canonical
   verifier recipe set. Use `canonical_verifier.py status` after a disconnect;
   resume only after the previous verifier supervisor and recipe process group
   are confirmed stopped and the recorded HEAD/recipe definitions still match.
8. After creating one PR, observe that exact PR head with
   `ci_waiter.py wait --head-sha <expected-pr-head-sha>` and its 30-minute
   bound. It only reads GitHub. A changed head, terminal failure, or timeout is
   not green; do not merge it.
9. Verify the final result from durable Git and PR state: fetch `origin`, check
   the PR's current head and merged state with `gh pr view`, confirm clean local
   `main == origin/main`, and prove the task branch head and seed are ancestors
   of `origin/main`. The recovery helper requires a task branch commit beyond
   the seed before it reports the assignment merged. Git ancestry can recognize
   a completed implementation merge even when the controller missed the final
   Codex JSONL event.

## Recovery matrix

| Situation | Durable authorities | Action |
| --- | --- | --- |
| SSH disconnect while Codex still runs | Branch lock, session process group, JSONL, stderr, Git branch/HEAD | Reconnect and keep observing the existing run. |
| Controller restarts while Codex still runs | External owner record, branch lock, `codex_session status`, Git refs | Resume observation. Never start a second process. |
| Codex exits nonzero before seed | Terminal result, bounded trace, assignment/control SHA, task branch and main refs | If the process group is dead, continue the same assignment from the verified pre-seed state. Create the seed only if it is absent; do not replace one that exists. |
| Codex exits nonzero after an implementation commit but before a PR | Terminal result, trace, branch log/HEAD, seed ancestry, checkpoint | After termination is proven, use an explicit continuation prompt naming the current HEAD. Preserve commits and review state; do not reseed, rebase, or recreate the branch. |
| Canonical verifier still runs after SSH disconnect | Verifier `run.json`, recipe process group, per-recipe logs, recorded Git HEAD | Keep observing. Resume only after the prior supervisor and recipe group stop and the verifier's same-HEAD checks pass. |
| CI waiter times out while checks remain queued | Wait summary/observations, PR head, GitHub check-run states | Do not merge or trigger/rerun CI. Report the bounded timeout and queued checks as a blocker. |
| PR head changes after a correction in this assignment | Local branch HEAD, PR head SHA, checkpoint, canonical/verifier result | Keep the same PR. Rerun required verification and a bounded CI wait for the new exact head before merge. |
| `origin/main` advances unexpectedly | Fetched `origin/main`, recorded start-main SHA, task branch HEAD | Stop and report the new SHA. Do not rebase, reset, or guess whether the assignment is still current. |
| Only the seed commit appears merged to main | Task branch commit count after start-main, `origin/main`, PR state | Do not report the assignment complete. Stop and inspect why implementation changes were not included. |
| PID metadata is stale after process exit | `/proc` process-group identity, terminal result, lock state, trace, Git refs | `stale` means the recorded group is gone but its result is missing: inspect trace and Git, then continue only with an explicit prompt. `invalid` or unverifiable identity is a blocker. |
| Merge completed but final Codex output was missed | `gh pr view`, `origin/main`, branch/seed ancestry, clean local `main` | Recognize completion from Git/PR state, write the merged checkpoint, and stop. Do not launch a continuation. |

## Continuation prompts

Launch a continuation only after the previous run has a terminal result or a
`stale` state proving its process group is gone. The helper additionally checks
that the previous branch lock is free, the new run ID is fresh, and
`--continuation-from` names the exact last run. The continuation prompt must
include:

- the same immutable control SHA and task ID;
- current branch and HEAD, main SHA, PR number/head/state, CI state, and highest
  lifecycle phase from durable sources;
- an instruction to continue the existing lifecycle, not recreate the seed,
  rebase, or recreate the PR;
- an instruction to preserve the review/PR, rerun required verification after
  corrections, and keep the issued scope unchanged.

Use `execution_recovery.py materialize --continuation-from <run-id>
--continuation-state-file <external-json>` to make a continuation prompt. The
state JSON has only fixed, validated fields; it accepts no arbitrary note text.
The helper rejects a continuation when its local branch/main SHAs no longer
match the state file. Check PR and CI fields against GitHub before materializing.
The state file contains `branch`, `branch_head`, `main_head`, `pr_number`,
`pr_head_sha`, `pr_state`, `ci_state`, and `lifecycle_phase`; use `null` for the
PR number/head only when no PR exists. For example, after a queued-check timeout
on an open PR, preserve that PR and head in the continuation file, then:

```bash
python tools/agent/execution_recovery.py materialize \
  --repo <repo_path> --control-sha <immutable-control-sha> \
  --manifest <manifest-path> --task <task-id> \
  --task-order <comma-separated-order> \
  --start-main-sha <expected-origin-main-sha> \
  --continuation-from <previous-run-id> \
  --continuation-state-file <external-state-root>/recovery-state.json \
  --output <external-state-root>/prompts/<task>-continuation-1.md

python tools/agent/execution_recovery.py start \
  --repo <repo_path> --branch <assignment-branch> \
  --run-id <new-fresh-run-id> \
  --prompt-file <external-state-root>/prompts/<task>-continuation-1.md \
  --state-dir <external-state-root> \
  --control-sha <immutable-control-sha> --task <task-id> \
  --continuation-from <previous-run-id>
```

Never use `codex resume --last`; resume a Codex session only when its exact
identity is known and the durable state proves it is not already running.

## Scope and pilot status

The helper is U24/POSIX-only and adds no runtime dependency. It does not manage
SSH credentials, Codex login, GitHub writes, pushes, PR creation, CI reruns, or
merges. Raw protocol commands remain available when these helpers are absent,
but the controller must apply the same lifecycle checks and duplicate-run
rules.

This integration is exercised with deterministic fake Codex and `gh` processes
and temporary Git repositories. The batch that introduced it used local shell
execution under the configured local account; it did not exercise a live SSH
transport or delegated Codex CLI session, so no real SSH-Codex pilot is claimed.
