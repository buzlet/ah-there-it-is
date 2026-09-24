# Autonomous batch manifest: post-0023 retrieval fix + Stage 26

Batch ID: `post-0023-stage26-2026-09-24`  
Mode: `serial-merge`  
Control branch: `queue/post-0023-stage26-batch`  
Protocol: `agent-tasks/common/v5-batch.md`

The immutable control SHA is supplied externally at launch.

## Repository and execution

- Repository: `buzlet/ah-there-it-is`
- Device: `u24-gpt`
- Merge method: merge commit
- Unexpected main advance after batch start: stop unless the user explicitly authorizes integrating that exact external commit and repeating the full current-task lifecycle
- Task failure: stop
- Reordering/skipping: forbidden

## Start prerequisite

Start only when current `origin/main` equals:

`789dea44c726935de76e66ca8d1f22a911756431`

and contains:
- completed Assignment 0023;
- PR #48 decision records;
- approved `agent-tasks/designs/stage26-location-truth.md`.

If main differs before start, stop and report the new SHA.

## Tasks

### 0024 — bounded FTS candidate-starvation fix

Branch: `feat/search-fts-candidate-starvation`  
Spec source: `agent-tasks/batches/post-0023-stage26/0024-search-fts-candidate-starvation.md`  
Assignment destination: `agent-tasks/assignments/0024-search-fts-candidate-starvation.md`

### 0025 — Stage 26 storage model + portable-v2

Branch: `feat/stage26-location-truth-storage`  
Spec source: `agent-tasks/batches/post-0023-stage26/0025-stage26-location-truth-storage.md`  
Assignment destination: `agent-tasks/assignments/0025-stage26-location-truth-storage.md`  
Depends on: successfully merged 0024.

### 0026 — Stage 26 domain transitions + invariants

Branch: `feat/stage26-location-truth-domain`  
Spec source: `agent-tasks/batches/post-0023-stage26/0026-stage26-location-truth-domain.md`  
Assignment destination: `agent-tasks/assignments/0026-stage26-location-truth-domain.md`  
Depends on: successfully merged 0025.

### 0027 — Stage 26 agent tool contract

Branch: `feat/stage26-location-truth-agent`  
Spec source: `agent-tasks/batches/post-0023-stage26/0027-stage26-location-truth-agent.md`  
Assignment destination: `agent-tasks/assignments/0027-stage26-location-truth-agent.md`  
Depends on: successfully merged 0026.

### 0028 — Stage 26 browser UX + final integration

Branch: `feat/stage26-location-truth-browser`  
Spec source: `agent-tasks/batches/post-0023-stage26/0028-stage26-location-truth-browser.md`  
Assignment destination: `agent-tasks/assignments/0028-stage26-location-truth-browser.md`  
Depends on: successfully merged 0027.

## Fixed decisions

The agent must implement, not reopen, the decisions in:
- `agent-tasks/designs/stage26-location-truth.md`;
- `agent-tasks/designs/post-0023-decisions.md`.

In particular:
- portable-v2 with v1 import compatibility;
- explicit reactivation;
- terminal Items searchable;
- browser catalog active-by-default;
- no fuzzy/transliteration/morphology/embeddings;
- coverage remains report-only.

## End boundary

After 0028 merges, stop.

Do not start duplicate/quantity splitting, undo, hard delete, trace retention, automated backup scheduling, remote-auth/multi-user work, or new retrieval algorithms.
