# Autonomous batch manifest: Windows Git Bash implementation-host enablement

Batch ID: `windows-git-bash-enablement-2026-09-24`  
Mode: `serial-merge`  
Control branch: `queue/windows-git-bash-enablement-v2`  
Execution protocol for this enabling task: `agent-tasks/common/v5-batch.md`

The immutable control SHA is supplied externally at launch.

## Purpose

This is a one-assignment enablement batch.

Assignment 0029 itself runs on the existing trusted U24 execution path. Its output prepares a new host-aware v6 protocol and platform-neutral verification harness so later implementation assignments may explicitly select either:

- `u24-bash`;
- `windows-git-bash`.

## Start prerequisite

The prior Stage 26 batch is complete.

Start Assignment 0029 only when current `origin/main` is exactly:

`f5a05fa4b723ed1bca37b8137f445594f58fdebd`

This is merge PR #53 / completed Assignment 0028.

Also verify:

- `agent-tasks/reviews/0028-r1.md` exists on current main;
- Stage 26 is factually complete in current strategy/status docs;
- PR #53 final implementation head had successful application CI;
- local `main` is clean and equals `origin/main`.

If main has advanced before 0029 starts, stop and report the new SHA rather than guessing whether the issued enablement assignment remains current.

## Task

### 0029 — Windows Git Bash implementation host enablement

Branch: `feat/windows-git-bash-implementation-host`  
Spec source: `agent-tasks/batches/windows-git-bash-enablement/0029-windows-git-bash-host.md`  
Assignment destination: `agent-tasks/assignments/0029-windows-git-bash-host.md`

Create the just-in-time seed from the exact start main above and execute normal v5/v4 lifecycle on U24.

## Execution reliability for this enabling task

The Stage 26 reviews showed repeated verification invocation retries caused by shell-state/environment assumptions, especially venv/PATH selection and ad-hoc canonical command arguments.

For Assignment 0029 itself:

- do not rely on shell activation persisting across Remote Commander calls;
- each independent command batch must explicitly enter the repo and prepend the project venv to PATH;
- invoke canonical Just recipes exactly by recipe name/defaults unless this assignment explicitly requires a non-default argument;
- do not use an indefinite interactive CI watcher.

These rules are also requirements for the resulting v6 protocol.

## End boundary

After 0029 merges, stop.

Do not claim Windows host validation merely from U24 tests. The first real `windows-git-bash` implementation assignment is a separate pilot using the newly merged v6 protocol.
