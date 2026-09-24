# Implementation + verification protocol v7: selected host and execution channel

Protocol v7 carries forward the immutable-seed, assignment, autonomous-batch, verification, PR/CI/merge and stop semantics of v4/v5/v6. Historical protocol files remain unchanged.

The v7 change is execution topology: **host profile** and **execution channel** are selected independently by the launcher.

## Launcher contract

The launcher must explicitly provide both:

```text
host_profile: <profile>
execution_channel: <channel>
```

Supported host profiles:

- `u24-bash`
- `windows-git-bash`

Supported execution channels:

- `remote-commander`
- `ssh-codex`

Initially supported combinations:

| host_profile | execution_channel | status |
| --- | --- | --- |
| `u24-bash` | `remote-commander` | established |
| `windows-git-bash` | `remote-commander` | prepared; native Windows pilot still required |
| `u24-bash` | `ssh-codex` | supported by this protocol; first batch using it is the operational pilot |
| `windows-git-bash` | `ssh-codex` | unsupported; stop |

The agent/controller must never infer, change or silently fall back from the selected pair.

## Common lifecycle

Regardless of channel, preserve all v6 lifecycle invariants:

- exact control SHA / assignment bytes;
- clean/current main prerequisite;
- one immutable seed commit;
- no amend/rebase/squash/reset-away/force rewrite;
- implementation after seed;
- focused then complete canonical verification;
- review record;
- one implementation PR;
- bounded CI correction loop;
- merge commit;
- post-merge clean main and seed ancestry proof;
- no roadmap/product authority;
- unexpected external main advance is a stop condition.

The canonical local verification set remains:

```text
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
just provider-contract
```

## Channel: remote-commander

For `remote-commander`, use the v6 host behavior unchanged.

Required launcher fields are the v6 fields for the selected host, including explicit device and repository path.

All repository/file/terminal/Git/test/GitHub work uses Remote Commander.

## Channel: ssh-codex on U24

This channel means the current chat/controller supervises an SSH session to U24 and delegates implementation work to **Codex CLI running on U24**.

Required launcher fields:

```text
host_profile: u24-bash
execution_channel: ssh-codex
ssh_target: <explicit SSH config target or user@host>
repo_path: <absolute U24 repository path>
codex_bin: <explicit command/path, normally codex>
```

Do not store SSH credentials, Codex authentication material or tokens in the repository, control branch, prompt files, logs or review records.

### Responsibility split

The chat/controller owns:

- opening/reopening SSH transport;
- read-only preflight/status inspection;
- constructing the exact issued prompt from control SHA/manifest;
- starting Codex;
- reading structured Codex output;
- detecting exit/timeout/disconnection;
- requesting status or terminating a stuck Codex process;
- validating durable repository/PR/CI state after Codex returns.

Codex owns the assignment implementation lifecycle:

- repository edits;
- Git commits/pushes;
- tests and canonical verification;
- review record;
- PR/CI correction work;
- merge and final main synchronization,

subject to the same issued assignment and protocol constraints.

The controller must not race Codex by making competing repository mutations while Codex is active.

### SSH/Codex preflight

Before launching Codex:

1. SSH connection succeeds non-interactively or through the user's already-authorized SSH setup.
2. `repo_path` exists and is the expected Git repository.
3. Establish the U24 v6 prelude explicitly:
   ```bash
   cd "$repo_path"
   export PATH="$PWD/.venv/bin:$PATH"
   ```
4. Project Python resolves inside `.venv/bin` and reports `os.name == "posix"`.
5. `git`, `just`, and `$codex_bin --version` succeed.
6. `$codex_bin login status` reports an authenticated local Codex state.
7. Worktree/main/control prerequisites required by the issued assignment are satisfied.

`codex login status` is only a local preflight indication. The first real Codex request is authoritative for whether remote authentication/service access actually works. On authentication failure, stop and report it; do not initiate login, inspect `auth.json`, or print credentials.

### Codex invocation contract

Use Codex non-interactively.

The preferred transport is:

```text
codex exec --json --full-auto -
```

with the exact task prompt supplied on stdin.

Reasons:

- `exec` is non-interactive;
- `--json` emits structured JSONL events;
- stdin avoids shell-quoting the full assignment prompt;
- `--full-auto` permits the issued repository implementation work.

Do not use the interactive TUI as the automation transport.

Do not use flags that bypass all sandbox/approval protections more broadly than `--full-auto` unless a future issued assignment explicitly authorizes them.

### Prompt authority

The Codex prompt must identify:

- repository;
- protocol path `agent-tasks/common/v7.md`;
- selected host/channel;
- immutable control SHA / manifest or exact single assignment;
- branch/task order;
- stop rules;
- requirement to return the compact protocol report.

Codex must read exact task/control bytes from Git at the supplied control SHA where the batch protocol requires it.

The controller may restate execution-channel mechanics but must not paraphrase or mutate the issued assignment semantics.

### Structured trace and durable state

For each Codex assignment process:

- preserve stdout JSONL;
- preserve stderr separately;
- preserve process exit status;
- keep these outside the Git worktree in an OS/user state directory, not `/tmp`;
- never commit traces;
- redact/avoid secrets rather than post-processing secret-bearing traces.

A future helper may manage this state, but the protocol does not require one particular implementation.

### Connection loss and resume

An SSH disconnect is **not** proof that Codex failed.

After transport loss:

1. reconnect;
2. inspect durable process/run state and repository state;
3. if the original Codex process is still running, continue observing it rather than launch a duplicate;
4. if it exited, inspect its exit code/trace and durable Git/PR state;
5. never start a second implementation process against the same branch until the first is proven stopped.

Codex session resume features may be used only when the exact session identity is known and doing so cannot duplicate an already-running process. Repository/PR durable state remains authoritative.

### Time bounds

Do not equate silence with failure.

However, every supervised Codex process must have observable progress and a finite control policy:

- controller status checks are bounded and non-interactive;
- no infinite SSH/read loop;
- normal long verification/CI activity is allowed;
- if there is no new structured output and no durable state change for 30 minutes, perform one diagnostic status inspection;
- do not kill solely because a test command is legitimately still running;
- if the process is alive but cannot be distinguished from a hang after diagnostic inspection, report a blocker rather than start a duplicate;
- CI waiting keeps the v6 30-minute-per-PR-head bound.

## Windows Git Bash

Windows host behavior remains exactly as defined by v6 for `windows-git-bash + remote-commander`.

This protocol does not authorize `windows-git-bash + ssh-codex`.

## Review/report additions for ssh-codex

A review record executed through `ssh-codex` additionally records:

- Codex CLI version;
- execution channel;
- whether the SSH connection was interrupted;
- number of Codex process launches for the assignment;
- whether any session resume was used;
- controller-observed timeout/hang diagnostics, if any.

Do not record account IDs, tokens, auth file contents, SSH secrets or private key paths.

## First ssh-codex pilot

The first real batch launched under `u24-bash + ssh-codex` is an operational pilot.

It must not weaken normal assignment verification because the execution channel is new. Any channel-specific failure is fixed as tooling/process work or reported as a blocker; application assertions are not relaxed to make the channel appear successful.
