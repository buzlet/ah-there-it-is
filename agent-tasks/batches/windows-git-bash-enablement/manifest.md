# Autonomous batch manifest: Windows Git Bash implementation-host enablement

Batch ID: `windows-git-bash-enablement-2026-09-24`  
Mode: `serial-merge`  
Control branch: `queue/windows-git-bash-enablement`  
Execution protocol for this enabling task: `agent-tasks/common/v5-batch.md`

The immutable control SHA is supplied externally at launch.

## Purpose

This is a one-assignment enablement batch.

Assignment 0029 itself runs on the existing trusted U24 execution path. Its output prepares a new host-aware v6 protocol and platform-neutral verification harness so later implementation assignments may explicitly select either:

- `u24-bash`;
- `windows-git-bash`.

## Start prerequisite

Do not start this batch until Assignment 0028 from control SHA
`29bfba2e372207c8f71b6cbe783fa388689cca0f`
has successfully merged.

At start:

- current `origin/main` must contain `agent-tasks/reviews/0028-r1.md`;
- Stage 26 must be factually complete in current strategy/status docs;
- local `main` must be clean and equal `origin/main`.

The exact post-0028 main SHA is intentionally not pre-issued.

If 0028 did not merge successfully, stop.

## Task

### 0029 — Windows Git Bash implementation host enablement

Branch: `feat/windows-git-bash-implementation-host`  
Spec source: `agent-tasks/batches/windows-git-bash-enablement/0029-windows-git-bash-host.md`  
Assignment destination: `agent-tasks/assignments/0029-windows-git-bash-host.md`

Create the just-in-time seed from the then-current post-0028 `main` and execute normal v5/v4 lifecycle on U24.

## End boundary

After 0029 merges, stop.

Do not claim Windows host validation merely from U24 tests. The first real `windows-git-bash` implementation assignment is a separate pilot using the newly merged v6 protocol.
