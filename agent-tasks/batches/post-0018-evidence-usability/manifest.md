# Autonomous batch manifest: post-0018 evidence and usability

Batch ID: `post-0018-evidence-usability-2026-09-24`  
Mode: `serial-merge`  
Control branch: `queue/post-0018-autonomous-batch`  
Protocol: `agent-tasks/common/v5-batch.md`

The immutable control SHA is supplied externally at launch because a commit cannot contain its own SHA.

## Repository and execution

- Repository: `buzlet/ah-there-it-is`
- Device: `u24-gpt`
- Merge method: merge commit
- Unexpected main advance after batch start: stop unless the user explicitly authorizes integrating that exact external commit and rerunning the full current-task lifecycle
- Task failure: stop
- Reordering/skipping: forbidden

## Start prerequisite

This batch may start immediately only when current `origin/main` equals:

`9420eaf5784912604e8351b2b45a8a6bdfe40832`

and contains the completed post-0013 batch result.

If `main` has advanced before batch start, stop and report the new SHA rather than guessing whether the batch specs remain current.

## Tasks

### 0019 — historical Event evidence snapshots

Branch: `feat/hardening-event-evidence-snapshots`  
Spec source: `agent-tasks/batches/post-0018-evidence-usability/0019-event-evidence-snapshots.md`  
Assignment destination: `agent-tasks/assignments/0019-event-evidence-snapshots.md`

### 0020 — browser Activity timeline

Branch: `feat/browser-activity-timeline`  
Spec source: `agent-tasks/batches/post-0018-evidence-usability/0020-browser-activity-timeline.md`  
Assignment destination: `agent-tasks/assignments/0020-browser-activity-timeline.md`  
Depends on: successfully merged 0019.

### 0021 — bounded agent conversation context

Branch: `feat/hardening-bounded-conversation-context`  
Spec source: `agent-tasks/batches/post-0018-evidence-usability/0021-bounded-conversation-context.md`  
Assignment destination: `agent-tasks/assignments/0021-bounded-conversation-context.md`  
Depends on: successfully merged 0020.

### 0022 — non-loopback serve guard

Branch: `feat/hardening-nonlocal-serve-guard`  
Spec source: `agent-tasks/batches/post-0018-evidence-usability/0022-nonlocal-serve-guard.md`  
Assignment destination: `agent-tasks/assignments/0022-nonlocal-serve-guard.md`  
Depends on: successfully merged 0021.

### 0023 — offline retrieval robustness baseline

Branch: `feat/retrieval-robustness-baseline`  
Spec source: `agent-tasks/batches/post-0018-evidence-usability/0023-retrieval-robustness-baseline.md`  
Assignment destination: `agent-tasks/assignments/0023-retrieval-robustness-baseline.md`  
Depends on: successfully merged 0022.

## Product boundary

These assignments deliberately do **not** define product Stage 26 location-truth semantics.

Do not implement or infer:
- unknown vs taken/in-use vs disposed lifecycle semantics;
- migration of old null locations into a new lifecycle state;
- identical-instance/quantity policy;
- location suggestions whose meaning depends on that lifecycle decision;
- delete/retirement policy;
- fuzzy matching, transliteration, stemming, embeddings or vector search.

After 0023 merges, stop and return the batch report.
