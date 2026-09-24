# Agent execution tools

## Durable Codex session runner

`tools/agent/codex_session.py` is a stdlib-only U24/POSIX helper for supervising
non-interactive Codex CLI work across an SSH disconnect. It does not belong to
the installed application package and does not automate Codex login.

The controller supplies a fresh, immutable run ID, repository path, prompt file,
external state directory, and Codex executable. The prompt file is passed as
stdin to `codex exec --json --full-auto -`; the runner never shell-interpolates
the prompt and stores only its SHA-256 digest. Use a state path under the
account's user state directory, outside the worktree and outside `/tmp`, for
example `$HOME/.local/state/ah-there-it-is/codex-runs`.

Example:

```bash
python tools/agent/codex_session.py start \
  --run-id post-0029-0030-attempt-1 \
  --repo /home/gpt/projects/ah-there-it-is \
  --prompt-file /home/gpt/.local/state/ah-there-it-is/prompts/0030.md \
  --state-dir /home/gpt/.local/state/ah-there-it-is/codex-runs \
  --codex-bin codex
```

Each run creates one private directory containing `metadata.json`,
`stdout.jsonl`, `stderr.log`, and an atomic `result.json` when terminal.
Run IDs cannot be reused. The runner starts a detached supervisor session,
records its PID, process group, and Linux process start time, and reports
`running`, `completed` with an exit code, `failed`, `terminated`,
`stale`, or `invalid` state as JSON.

Inspect a run or read a bounded tail:

```bash
python tools/agent/codex_session.py status \
  --run-id post-0029-0030-attempt-1 \
  --state-dir /home/gpt/.local/state/ah-there-it-is/codex-runs

python tools/agent/codex_session.py tail \
  --run-id post-0029-0030-attempt-1 \
  --state-dir /home/gpt/.local/state/ah-there-it-is/codex-runs \
  --stream stdout --max-bytes 8192 --max-lines 100
```

Terminate only the named run. The helper sends SIGTERM to its process group,
waits for the bounded grace period, then escalates to SIGKILL if any non-zombie
member remains:

```bash
python tools/agent/codex_session.py terminate \
  --run-id post-0029-0030-attempt-1 \
  --state-dir /home/gpt/.local/state/ah-there-it-is/codex-runs
```

A missing terminal result plus a dead process group is reported as stale; a
PID number alone is never considered proof that the process is running. The
raw `codex exec --json --full-auto -` invocation remains a valid protocol
fallback when a controller does not use this helper.

## Lifecycle preflight and checkpoints

`tools/agent/lifecycle_checkpoints.py` is a stdlib-only, read-only Git preflight,
seed verifier, and external lifecycle journal. It does not fetch refs or mutate
Git history. Fetch control and origin refs explicitly before asking it to check
them.

A preflight reads the manifest and task specification as Git blobs at the
supplied immutable control SHA. Supply the expected start-main SHA and the
manifest task order when the batch defines them. The JSON result contains every
check and the selected task's exact branch, source, and assignment destination.
An existing target task branch is a blocker unless the caller explicitly allows
it for a repeated inspection.

```bash
python tools/agent/lifecycle_checkpoints.py preflight \
  --repo /home/gpt/projects/ah-there-it-is \
  --expected-repo-path /home/gpt/projects/ah-there-it-is \
  --control-branch queue/example-batch \
  --control-sha <immutable-control-sha> \
  --manifest agent-tasks/batches/example/manifest.md \
  --task 0031 \
  --expected-start-main-sha <expected-origin-main-sha> \
  --expected-task-order 0030,0031,0032

python tools/agent/lifecycle_checkpoints.py verify-seed \
  --repo /home/gpt/projects/ah-there-it-is \
  --branch feat/example-task \
  --base-sha <start-main-sha> \
  --control-sha <immutable-control-sha> \
  --assignment-source agent-tasks/batches/example/task.md \
  --assignment-destination agent-tasks/assignments/task.md
```

Checkpoint commands emit one JSON object per invocation. Store the state outside
the repository, for example under
`$HOME/.local/state/ah-there-it-is/lifecycle-checkpoints`. The finite phase
vocabulary advances in order. A regression requires the next explicit
`--correction-iteration`; the journal keeps the highest phase and records the
correction in both histories. Checkpoint writes use a same-directory temporary
file, fsync, and atomic replacement. `checkpoint-status` reports `current`,
`stale`, `missing`, or `invalid` by comparing the saved branch and HEAD with
local Git state. It reports durable facts only; it does not decide whether work
should be rerun or treat a stale checkpoint as proof that a process stopped.

```bash
python tools/agent/lifecycle_checkpoints.py checkpoint \
  --repo /home/gpt/projects/ah-there-it-is \
  --state-dir "$HOME/.local/state/ah-there-it-is" \
  --assignment 0031 --phase seeded

python tools/agent/lifecycle_checkpoints.py checkpoint-status \
  --repo /home/gpt/projects/ah-there-it-is \
  --state-dir "$HOME/.local/state/ah-there-it-is" \
  --assignment 0031
```

## Canonical verification supervisor

`tools/agent/canonical_verifier.py` supervises exactly these existing recipes,
in this fixed order: `check`, `migration-check`, `corpus-check`,
`scenario-check`, `scenario-eval`, `retrieval-eval`, and `provider-contract`.
It calls `just <recipe>` directly from the supplied repository; it does not
reimplement any recipe or change CI.

Each run uses a new state directory outside the worktree. The default timeout
is one hour per recipe. Stdout and stderr are stored separately per attempt in
bounded logs (up to 1 MiB per stream); truncation metadata and both ends of a
large stream are kept. Atomic `run.json` updates preserve completed-check state,
and `summary.json` is atomically written when the run reaches a terminal result.
A repository-scoped process lock prevents two verifier runs from running at the
same time.

```bash
python tools/agent/canonical_verifier.py start \
  --repo /home/gpt/projects/ah-there-it-is \
  --state-dir "$HOME/.local/state/ah-there-it-is/canonical-runs/0032-final-head"

python tools/agent/canonical_verifier.py status \
  --state-dir "$HOME/.local/state/ah-there-it-is/canonical-runs/0032-final-head"

python tools/agent/canonical_verifier.py resume \
  --repo /home/gpt/projects/ah-there-it-is \
  --state-dir "$HOME/.local/state/ah-there-it-is/canonical-runs/0032-final-head"
```

A timed-out recipe is stopped by signaling its process group, then escalating
after a short grace interval. Status reports a live supervisor or a still-live
orphaned recipe process group so a second verifier is not started. Resume only
continues after the previous supervisor has stopped, when the recorded Git HEAD
and fixed recipe definitions still match and every recorded check succeeded. An
interrupted recipe without a durable success record is run again; successful
checks are reused only from a valid same-HEAD prefix.

## Bounded GitHub CI waiter

`tools/agent/ci_waiter.py` is a read-only observer for checks on one exact
pull-request head. For v7 assignments, use it as the preferred CI waiting path
when the helper is available. It uses the authenticated `gh` CLI through
non-interactive `gh api` GET requests; it does not inspect credentials or write
them to output.

Before every observation cycle, and again after reading checks, it verifies
that the PR still points to the expected head SHA. Check runs are requested for
that exact commit, along with legacy commit status contexts. A changed PR head
returns `head_changed`. The waiter distinguishes queued/in-progress checks,
successful `success`/`neutral`/`skipped` conclusions, other terminal
conclusions, checks that have not registered yet, and an overall timeout. Empty
check results never count as green; the default registration grace period is
120 seconds.

The default overall timeout is 30 minutes. Poll intervals are bounded to
1–300 seconds (default 15). The registration grace period is bounded to
0–600 seconds. Every `gh api` call also has a finite request timeout. The
helper only issues API reads; rerun, cancel, push, and merge actions remain
outside its side-effect boundary.

```bash
python tools/agent/ci_waiter.py wait --repo buzlet/ah-there-it-is --pr 58 --head-sha <expected-pr-head-sha> --timeout-seconds 1800 --poll-interval-seconds 15 --state-dir "/home/gpt/.local/state/ah-there-it-is/ci-waits/0033-pr-58-head"
```

Use a new state directory outside the worktree for each wait. When supplied,
`observations.jsonl` records credential-free polling snapshots and
`summary.json` is atomically written with the final result. Without a state
directory, the CLI still emits one concise JSON result to stdout. Exit status is
zero only for `success`; all other final states return nonzero.
