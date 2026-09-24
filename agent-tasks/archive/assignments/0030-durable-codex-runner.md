# Assignment 0030: durable Codex session runner

Protocol: `agent-tasks/common/v7.md`.

Branch: `feat/agent-durable-codex-runner`

## Objective

Add a small stdlib-only U24 helper that can launch and supervise non-interactive Codex CLI work durably across SSH disconnects.

The helper supports the v7 `u24-bash + ssh-codex` channel. It is development/process tooling, not application runtime functionality.

## Location

Use a clearly non-application tooling namespace such as:

`tools/agent/codex_session.py`

with focused tests.

Do not add the helper to the installed application console scripts.

## Required commands

Provide equivalent CLI operations:

- `start`
- `status`
- `tail`
- `terminate`

Exact argparse spelling may be chosen coherently and documented.

## Start behavior

Inputs must include:

- immutable caller-selected `run_id`;
- repository path;
- prompt file;
- external state directory;
- Codex executable/command.

The runner launches exactly:

`codex exec --json --full-auto -`

or the supplied equivalent Codex binary with those arguments.

The prompt is fed through stdin from the supplied prompt file. Do not shell-interpolate the prompt.

Launch must survive loss of the initiating SSH connection. A POSIX detached process/session is appropriate.

The caller-facing `start` command must return promptly with machine-readable state identifying the run and managed process.

## Durable run state

Each `run_id` gets one immutable run directory under the caller-supplied external state directory.

Store, at minimum:

- metadata JSON;
- Codex stdout JSONL;
- stderr log;
- terminal exit/result JSON when complete.

Metadata includes non-secret operational fields such as:

- run ID;
- PID/process-group identity needed for supervision;
- repo path;
- Codex command/version when available;
- prompt SHA-256, not a copied prompt body;
- started timestamp;
- lifecycle status.

Never copy authentication files, tokens, environment secrets or SSH material.

Never write run state into the Git worktree.

## Duplicate protection

A run ID is never reused.

If `start` sees an existing run directory, it must refuse rather than truncate/replace it.

Starting a second Codex process for the same run ID is impossible through the helper.

## Status

`status` returns concise machine-readable JSON distinguishing at least:

- running;
- completed with exit code;
- terminated;
- invalid/stale state.

A missing SSH connection is irrelevant once the process is launched.

Do not declare a PID alive solely because a PID number exists; use appropriate POSIX process checks and durable terminal state.

## Tail

Allow bounded reading of recent stdout JSONL or stderr without loading an unbounded trace.

Default to a reasonable bounded byte/line amount.

## Terminate

Terminate only the explicitly named run.

Use process-group-aware termination so descendants are not knowingly orphaned.

Attempt graceful termination first, then a bounded escalation if the group remains alive.

Record termination outcome durably.

## Worker/result integrity

The detached worker must write terminal state atomically enough that a controller can distinguish:

- still running;
- exited successfully;
- exited nonzero;
- terminated;
- runner/worker failure.

Do not require the parent SSH process to reap Codex in order to learn the result.

## Portability boundary

This helper is intentionally U24/POSIX-only in Assignment 0030.

Do not claim Windows support and do not add PowerShell.

## Tests

Use fake Codex executables/processes, not live model calls.

Cover:

- prompt stdin is passed byte-for-byte;
- JSONL/stderr capture;
- successful/nonzero exit;
- detached survival model;
- duplicate run rejection;
- bounded tail;
- graceful terminate/escalation;
- stale/invalid state;
- no worktree artifacts;
- no secret/environment dump.

## Documentation

Document how v7 SSH-Codex controllers can use the helper, while keeping raw `codex exec --json --full-auto -` a valid protocol fallback.

## Constraints

No inventory/application behavior changes, no dependency addition, no provider/model calls in tests, no auth/login automation, no protocol downgrade.

## Verification

Run focused tooling tests, then the full v7 canonical verification set.
