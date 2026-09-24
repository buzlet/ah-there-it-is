# Autonomous batch manifest: agent execution reliability

Batch ID: `post-0029-agent-execution-reliability-2026-09-24`  
Mode: `serial-merge`  
Protocol: `agent-tasks/common/v7.md`  
Control branch: `queue/post-0029-agent-execution-reliability`

The launcher supplies one supported v7 host/channel pair for the entire batch. The pair remains fixed for all five assignments.

## Allowed execution selections

### Established path

```text
host_profile: u24-bash
execution_channel: remote-commander
device: u24-gpt
repo_path: /home/gpt/projects/ah-there-it-is
```

### New SSH/Codex path

```text
host_profile: u24-bash
execution_channel: ssh-codex
ssh_target: <explicit SSH target>
repo_path: <absolute U24 repository path>
codex_bin: <explicit Codex CLI command/path>
```

Do not use Windows for this batch.

## Start prerequisite

Start only when current `origin/main` equals exactly:

`25453f291a3c0a8d3a5c77a6ef8adfc533226c62`

This is merge PR #55 and contains completed Assignment 0029 plus protocol v7.

Also require a clean local/main worktree before the first seed.

If main has advanced, stop and report the new SHA rather than guessing whether the issued batch remains current.

## Batch objective

Harden the implementation-agent execution layer before the next product-semantic gate.

This batch must not change inventory domain semantics. It addresses the operational failure modes already observed in long autonomous runs:

- SSH disconnects;
- uncertainty whether a Codex process is still running;
- duplicate launches after transport loss;
- lost shell/venv state;
- ad-hoc lifecycle prerequisite checks;
- long canonical verification with poor durable observability;
- unbounded/opaque CI waiting.

## Tasks

### 0030 — durable Codex session runner

Branch: `feat/agent-durable-codex-runner`  
Spec source: `agent-tasks/batches/post-0029-agent-execution-reliability/0030-durable-codex-runner.md`  
Assignment destination: `agent-tasks/assignments/0030-durable-codex-runner.md`

### 0031 — lifecycle preflight and checkpoints

Branch: `feat/agent-lifecycle-checkpoints`  
Spec source: `agent-tasks/batches/post-0029-agent-execution-reliability/0031-lifecycle-checkpoints.md`  
Assignment destination: `agent-tasks/assignments/0031-lifecycle-checkpoints.md`  
Depends on: 0030 merged.

### 0032 — structured canonical verification runner

Branch: `feat/agent-canonical-verifier`  
Spec source: `agent-tasks/batches/post-0029-agent-execution-reliability/0032-canonical-verifier.md`  
Assignment destination: `agent-tasks/assignments/0032-canonical-verifier.md`  
Depends on: 0031 merged.

### 0033 — bounded GitHub CI waiter

Branch: `feat/agent-bounded-ci-waiter`  
Spec source: `agent-tasks/batches/post-0029-agent-execution-reliability/0033-bounded-ci-waiter.md`  
Assignment destination: `agent-tasks/assignments/0033-bounded-ci-waiter.md`  
Depends on: 0032 merged.

### 0034 — execution recovery integration and pilot hardening

Branch: `feat/agent-execution-recovery-integration`  
Spec source: `agent-tasks/batches/post-0029-agent-execution-reliability/0034-execution-recovery-integration.md`  
Assignment destination: `agent-tasks/assignments/0034-execution-recovery-integration.md`  
Depends on: 0033 merged.

## Batch constraints

Do not implement:

- quantity/physical-instance semantics;
- undo/delete policy;
- retention/backup scheduling;
- authentication/multi-user;
- Windows SSH-Codex support;
- new retrieval algorithms;
- application/provider model behavior changes.

No new third-party runtime dependency is allowed.

## Stop policy

Use v7 stop conditions.

For `ssh-codex`, transport loss is not by itself a task failure. Reconnect and inspect durable state before deciding whether the original Codex process stopped. Never launch a duplicate implementation process against the same assignment branch.

After 0034 merges, stop and return one compact batch report.
