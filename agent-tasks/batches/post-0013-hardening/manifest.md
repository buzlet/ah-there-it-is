# Autonomous batch manifest: post-0013 hardening

Batch ID: `post-0013-hardening-2026-09-23`  
Mode: `serial-merge`  
Control branch: `queue/post-0013-autonomous-batch`  
Protocol source: `agent-tasks/common/v5-batch.md`

The immutable control SHA is supplied externally at launch because a commit cannot contain its own SHA.

## Repository and execution

- Repository: `buzlet/ah-there-it-is`
- Device: `u24-gpt`
- Merge method: merge commit
- Unexpected main advance after batch start: stop
- Task failure: stop
- Task reordering/skipping: forbidden

## Start prerequisite

Assignment 0013 is **not** part of this batch. It was already handed to a v4 implementation agent.

Before starting 0014:

- current `origin/main` must contain seed `99e6e1353bd9e9244435115f321ce07cc1023904` as an ancestor;
- `agent-tasks/reviews/0013-r1.md` must exist on current main;
- current main must represent the successfully merged Assignment 0013;
- record that SHA as `batch_start_main_sha`.

If Assignment 0013 is not successfully merged, do not start this batch.

## Tasks

### 0014 — Stage 24 atomic agent turn + committed receipts

Branch: `feat/stage24-atomic-turn-receipts`  
Spec source: `agent-tasks/batches/post-0013-hardening/0014-stage24-atomic-turn-receipts.md`  
Assignment destination: `agent-tasks/assignments/0014-stage24-atomic-turn-receipts.md`  
Depends on: successfully merged 0013.

For the 0014 seed also copy:
- `agent-tasks/common/v5-batch.md` to the same repository path;
- this manifest to `agent-tasks/batches/post-0013-hardening/manifest.md`.

### 0015 — Stage 25 idempotency crash consistency

Branch: `feat/stage25-idempotency-crash-consistency`  
Spec source: `agent-tasks/batches/post-0013-hardening/0015-stage25-idempotency-crash-consistency.md`  
Assignment destination: `agent-tasks/assignments/0015-stage25-idempotency-crash-consistency.md`  
Depends on: successfully merged 0014.

### 0016 — hardening: bounded high-cardinality reads

Branch: `feat/hardening-bounded-reads`  
Spec source: `agent-tasks/batches/post-0013-hardening/0016-bounded-high-cardinality-reads.md`  
Assignment destination: `agent-tasks/assignments/0016-bounded-high-cardinality-reads.md`  
Depends on: successfully merged 0015.

This maintenance assignment does **not** consume or redefine product Stage 26.

### 0017 — hardening: persisted trace/config privacy

Branch: `feat/hardening-trace-config-privacy`  
Spec source: `agent-tasks/batches/post-0013-hardening/0017-trace-config-privacy.md`  
Assignment destination: `agent-tasks/assignments/0017-trace-config-privacy.md`  
Depends on: successfully merged 0016.

This maintenance assignment does **not** consume or redefine product Stage 26.

### 0018 — hardening: restore rehearsal + semantic validation

Branch: `feat/hardening-restore-rehearsal`  
Spec source: `agent-tasks/batches/post-0013-hardening/0018-restore-rehearsal.md`  
Assignment destination: `agent-tasks/assignments/0018-restore-rehearsal.md`  
Depends on: successfully merged 0017.

This maintenance assignment does **not** consume or redefine product Stage 26.

## End boundary

After 0018 merges, stop.

Do not implement:
- Location truth / unknown-vs-in-use-vs-disposed semantics;
- identical-instance UX;
- evidence suggestions based on new lifecycle semantics;
- historical Event path snapshots;
- Activity UI;
- retrieval/fuzzy/embedding changes.

Those require a later orchestrator decision/batch.
