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
