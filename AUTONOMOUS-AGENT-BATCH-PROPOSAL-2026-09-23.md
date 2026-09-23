# Proposal: autonomous multi-assignment agent batches

**Project:** `buzlet/ah-there-it-is`  
**Date:** 2026-09-23  
**Status:** process proposal, not yet adopted

## Goal

Allow one implementation agent to work unattended for several hours across multiple pre-approved assignments without requiring the orchestrator between every merge, while preserving:

- immutable issued specifications;
- explicit architecture/product ownership by the orchestrator;
- stage-level review records;
- deterministic local verification;
- PR CI;
- merge-commit history;
- the ability to stop safely on a real design blocker.

The agent must gain **execution autonomy**, not **roadmap autonomy**.

## Recommended model: v5 batch executor

Keep protocol v4 as the per-assignment implementation contract.

Add a thin batch protocol above it. The batch protocol does not redefine implementation/testing rules; it only governs how an agent moves from one already-approved assignment to the next.

### Core idea

Before handoff, the orchestrator creates one immutable **batch control commit** containing:

- a batch manifest;
- the exact future assignment texts;
- branch names;
- dependency order;
- merge mode;
- stop/continue rules.

The control commit lives on a dedicated branch such as:

`queue/write-safety-2026-09-23`

and is referenced by immutable SHA in the launcher.

The implementation agent may not edit or reinterpret this control commit.

For the first task it can continue an already-seeded branch such as Assignment 0013.

After a task successfully merges, the batch protocol authorizes the agent to create the next branch itself from the **new current main**, using the exact next assignment text from the immutable control commit.

This avoids the main v4 obstacle: a future seed cannot be created in advance because `main` changes after every merge.

## Recommended execution mode: serial merge queue

For safety-critical or dependent work, use:

`mode: serial-merge`

Lifecycle:

1. execute Assignment N using normal v4 semantics;
2. local focused + canonical verification;
3. review record;
4. PR;
5. own CI/fix loop;
6. merge commit;
7. sync and verify `main`;
8. verify no unexpected external main commits appeared;
9. create Assignment N+1 branch from that exact new `main`;
10. create one immutable seed using the pre-issued assignment;
11. immediately execute it;
12. repeat until the manifest is complete or a stop condition fires.

Thus the agent can work for hours while every stage still has its own:
- seed;
- implementation commits;
- review record;
- PR;
- CI result;
- merge boundary.

The orchestrator is not needed between tasks because the next task was already selected and specified.

## Why not one giant integration PR by default

A second possible mode is:

`mode: integration-branch`

where several assignments are implemented as checkpoint commits on one branch and only one final PR is opened.

This saves CI time, but for the current roadmap it is not recommended because:

- Stage 23–25 modify safety and transaction semantics;
- failures become harder to localize;
- later stages can accidentally compensate for defects in earlier ones;
- there is no clean repository boundary proving each safety invariant independently;
- rollback of one stage becomes harder;
- the diff becomes substantially larger.

Use a single integration PR only for small, tightly coupled, low-risk tasks where intermediate merge boundaries provide little value.

## Current roadmap suitability

### Good autonomous batch: Assignments 0013–0015

The next three tasks form a clear dependency chain and are already architecturally decided.

#### Assignment 0013 / Stage 23
Write target safety:
- required nullable move target;
- independent write resolver;
- no score/singleton authorization;
- global canonical/alias conflict checks;
- atomic resolution re-check.

Already seeded as:
`feat/stage23-write-target-safety`

#### Assignment 0014 / Stage 24
Atomic agent turn + committed receipts:
- strict post-mutation rollback state machine;
- mutation receipts;
- authoritative `changes_applied`;
- persisted committed receipts on run log;
- no-op semantics;
- failed-turn conversation-context semantics.

Dependency:
`0013` must be merged successfully first.

#### Assignment 0015 / Stage 25
Idempotency crash consistency:
- reservation remains pre-execution;
- business state + completed run + committed receipts + request completion become one final keyed transaction;
- fault injection before commit / after commit before response / uncertain commit result;
- durable-state reconciliation through fresh transaction/connection;
- replay/concurrency tests;
- measure SQLite lock behavior across slow model rounds rather than redesigning architecture speculatively.

Dependency:
`0014` must be merged successfully first.

This is an excellent unattended several-hour batch.

### Do not include Stage 26 in the first autonomous batch

Stage 26 currently contains unresolved product/domain choices:

- unknown vs taken/in-use vs disposed;
- interaction with existing `ItemState`;
- migration semantics for old null locations;
- identical-instance UX;
- when suggestions are valid.

The accepted roadmap explicitly says **design before implementation**.

An autonomous implementation agent should stop before this boundary rather than invent these policies.

### Stage 27 also waits

Historical snapshots + Activity depend on decisions around truthful location/history semantics. It belongs in a later batch after Stage 26 design is fixed.

## Batch manifest

Suggested machine-readable + human-readable manifest:

```yaml
batch_id: write-safety-2026-09-23
protocol: agent-tasks/common/v5-batch.md
control_sha: <immutable control commit>
mode: serial-merge

repository: buzlet/ah-there-it-is
device: u24-gpt

expected_initial_main: <sha>

tasks:
  - assignment: 0013
    branch: feat/stage23-write-target-safety
    source: existing-seed
    depends_on: []

  - assignment: 0014
    branch: feat/stage24-atomic-turn-receipts
    source: batch-spec
    spec_path: agent-tasks/batches/write-safety-2026-09-23/0014.md
    depends_on: [0013]

  - assignment: 0015
    branch: feat/stage25-idempotency-crash-consistency
    source: batch-spec
    spec_path: agent-tasks/batches/write-safety-2026-09-23/0015.md
    depends_on: [0014]

policy:
  merge_method: merge
  unexpected_main_advance: stop
  dependent_task_failure: stop
  unrelated_task_failure: continue-if-authorized
  assignment_mutation: forbidden
  batch_spec_mutation: forbidden
```

The actual manifest format can remain Markdown if desired; the important part is that its semantics are explicit and testable.

## Just-in-time seed rule

For every task after the first:

1. previous task must be merged and local `main` clean;
2. fetch `origin/main`;
3. verify current `main` equals the previous task's merge result;
4. if another unlisted commit appeared, stop the batch;
5. create the next assignment branch from current `main`;
6. copy the exact assignment from `control_sha`;
7. apply only the predefined stage-status seed updates;
8. create exactly one seed commit;
9. record `seed_sha`;
10. continue with normal v4 implementation lifecycle.

This prevents stale pre-seeded branches while preserving immutable task issuance.

## Preventing the agent from becoming the orchestrator

The batch agent may:

- execute listed tasks;
- create the next listed branch;
- create the seed from the exact pre-issued spec;
- update factual completion status for a finished task;
- open/fix/merge its own PR;
- proceed to the next dependency-approved task.

It may not:

- add a task;
- remove a task;
- reorder dependent tasks;
- broaden assignment scope;
- choose a new architecture;
- change a pre-issued assignment;
- continue through a stated design blocker;
- substitute a different stage because one seems more convenient.

This is the key distinction between autonomous execution and autonomous product direction.

## Stop conditions

For a dependent serial batch, stop immediately when:

- an assignment exposes a materially unresolved architecture/product decision;
- required behavior conflicts with repository invariants;
- U24 becomes unavailable;
- canonical verification has a persistent unexplained failure;
- CI failure appears unrelated and remains after minimal retry;
- an unexpected external commit advances `main`;
- a provider/account/manual credential action becomes required;
- the next task's dependency did not merge successfully.

Do not skip a failed dependent task.

## Independent tasks

For unrelated tasks there are two useful policies.

### A. One agent, independent serial queue — recommended default

Even if tasks are independent, let one agent execute them sequentially with separate branches/PRs.

Advantages:
- simplest mental model;
- every new branch starts from current `main`;
- no stale branches;
- almost no merge conflict handling;
- unattended operation still works.

There is little wall-clock benefit in making one reasoning agent actively develop several branches at once.

### B. Parallel worktrees — only when parallelism is actually useful

Use multiple branches/worktrees concurrently only if:
- tasks touch clearly disjoint areas;
- tests can run concurrently without exhausting U24;
- either multiple agents are used, or the work is mostly long-running mechanical/test activity.

Suggested layout:

```text
/home/gpt/projects/ah-there-it-is-batch/
  task-0016/
  task-0017/
  task-0018/
```

Each worktree gets its own seeded branch.

Do not merge them all blindly. Merge one at a time; before each later merge:
- update/merge current `main` into that branch if the batch protocol explicitly allows it;
- rerun affected verification;
- require CI on the actual final PR head/base combination.

Parallel mode saves wall-clock time but costs substantially more conflict and validation complexity.

For this project, serial autonomous execution should remain the default.

## DAG support for mixed batches

A batch may contain dependencies:

```text
0013 → 0014 → 0015

             ┌→ maintenance-A
after 0015 ──┤
             └→ maintenance-B
```

The manifest can define:
- `depends_on`;
- `on_blocker: stop` for dependent tasks;
- `on_blocker: continue-independent` for unrelated tasks.

The agent does not infer the DAG. The orchestrator writes it.

## Progress and reporting

To avoid requiring chat interaction between tasks:

- each assignment keeps its normal `NNNN-r1.md`;
- the agent maintains an ephemeral local batch journal while working;
- after the final task, add one compact batch result file or return one final summary containing:
  - control SHA;
  - each assignment;
  - seed SHA;
  - PR;
  - merge SHA;
  - correction counts;
  - verification result;
  - blockers/skips.

Intermediate chat messages are unnecessary unless a stop condition fires.

## CI cost

With serial merge mode for three code stages:

- 3 implementation PRs;
- 3 full CI cycles;
- no seed push CI;
- no orchestrator duplicate local verification;
- no human intervention between stages.

This is slower than one giant PR but much safer for Stage 23–25.

If later batches contain several tiny low-risk tasks, integration-branch mode can be selectively used to reduce CI overhead.

## Recommended first autonomous batch

Prepare one batch control branch containing exact specs for:

1. existing Assignment 0013;
2. new Assignment 0014 — atomic turn + committed receipts;
3. new Assignment 0015 — idempotency crash consistency.

Use:
- serial merge;
- stop on any blocker in 0013–0015;
- stop on unexpected `main` advance;
- no Stage 26 work.

The user can then start the implementation agent once and leave it working until:
- all three assignments are merged, or
- the first genuine blocker is encountered.

## Example launcher

```text
Работай как autonomous batch implementation+verification agent проекта buzlet/ah-there-it-is.

Используй только Remote Commander на U24, устройство u24-gpt.

Batch control:
- branch: queue/write-safety-2026-09-23
- immutable control SHA: <sha>

Начни с уже подготовленной ветки feat/stage23-write-target-safety.

Прочитай agent-tasks/common/v5-batch.md и batch manifest по указанному control SHA.
Выполни весь разрешённый batch последовательно. Для каждой задачи используй полный v4 implementation/verification/PR/CI/merge lifecycle. После успешного merge самостоятельно создавай следующий seed только из заранее выданной спецификации batch manifest.

Не выбирай новые задачи и не меняй выданные спецификации. Остановись только при stop condition из batch protocol.

Верни один итоговый batch report либо компактный blocker report, если batch остановлен.
```

## Recommendation

Adopt the batch layer as a small **v5 wrapper around v4**, not as a rewrite of v4.

For the immediate roadmap, use a three-task serial batch for 0013–0015.

This gives the desired several hours of autonomous work while retaining independent safety boundaries and preventing the implementation agent from silently becoming the project architect.
