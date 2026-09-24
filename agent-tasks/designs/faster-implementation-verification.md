# Proposal: faster implementation-agent verification without reducing quality

Status: proposal only. No protocol or CI behavior changed by this document.

## Problem observed

The current lifecycle performs the same broad regression proof repeatedly:

1. focused tests during implementation;
2. complete local canonical verification before every PR;
3. complete application CI on every PR;
4. repeat the same pattern for every task in a serial autonomous batch.

Recent measurements on Assignment 0029 CI:

- complete application CI: about 3m33s wall clock;
- full pytest under coverage: about 2m59s;
- scenario evaluation: about 10.5s;
- retrieval evaluation: about 1.1s;
- migration/corpus/scenario structure checks: roughly seconds.

Recent assignments also commonly ran tens of focused tests before the complete local suite.

The dominant duplication is therefore not scenario/retrieval tooling. It is running the complete pytest regression suite locally and then again in CI for every small batch task.

## Principle

Do not remove independent quality guarantees.

Instead, assign each guarantee to the cheapest lifecycle boundary that can prove it:

- inner implementation loop → targeted/focused tests;
- task boundary → focused final verification + cheap structural checks;
- batch integration boundary → complete local host-sensitive verification when needed;
- merge boundary → one complete CI regression of the cumulative batch.

The final merged code still receives a complete regression proof.

## Proposed protocol mode: integrated batch

For a pre-issued, serial, internally coherent batch, use one batch implementation branch and one final PR instead of one PR per task.

Keep task specifications and commit boundaries explicit.

Example:

```text
batch seed/control
  |
  +-- task 0035 implementation commits
  +-- task 0035 checkpoint/review section
  +-- task 0036 implementation commits
  +-- task 0036 checkpoint/review section
  +-- task 0037 implementation commits
  +-- task 0037 checkpoint/review section
  +-- task 0038 implementation commits
  +-- task 0038 checkpoint/review section
  +-- task 0039 implementation commits
  |
  +-- complete final verification
  +-- one PR
  +-- one full CI
  +-- one merge commit
```

Every task remains separately identifiable in Git history, but GitHub/CI does not re-prove the entire repository five times.

### When integrated-batch mode is allowed

Only when all tasks:

- are pre-issued before implementation starts;
- are serial dependencies in one coherent area;
- contain no unresolved product/architecture gate between them;
- can safely remain unmerged until the full batch succeeds;
- do not require an externally consumed intermediate main state.

### When separate PRs remain required

Use the existing per-task PR lifecycle when:

- a task contains a schema/data migration whose result must become an independently accepted baseline before unrelated work;
- tasks are independent and useful separately;
- a task changes CI/release/security boundaries;
- the next task depends on external/manual verification of the previous one;
- a product decision gate exists between tasks;
- a task is high-risk enough that isolation is materially useful;
- the user explicitly requests per-task merges.

This keeps isolation where it actually buys safety.

## Verification tiers

### Tier 1 — implementation inner loop

After an edit, run only the smallest relevant tests.

Examples:

- service change → its service/domain tests;
- route/template change → corresponding web/browser tests;
- migration change → migration-focused tests;
- agent schema/dispatcher change → agent/provider-schema tests.

Do not rerun the whole focused set after every tiny correction.

Recommended loop:

1. run failing/specific test;
2. fix;
3. rerun that test;
4. when the logical change is complete, run the complete focused set once.

This preserves feedback quality while reducing repeated setup.

### Tier 2 — task checkpoint inside an integrated batch

At the end of each task:

Required:

- complete focused test set declared by the task;
- `python -m compileall -q src tests` or `just compile`;
- `git diff --check`;
- task-specific invariant checks.

Conditional only:

- migration check if migration/schema/storage code changed;
- scenario subset if scenario/application behavior changed;
- retrieval evaluation if retrieval/search behavior changed;
- provider schema tests if provider/tool schema changed;
- installed-wheel smoke if package/runtime/assets/migration packaging changed.

Do **not** run the complete 300+ test suite merely because a task checkpoint was reached.

Record the checkpoint in one batch review document.

### Tier 3 — final local batch verification

Before the batch PR:

Run the full local canonical suite only when it provides evidence not already supplied by CI.

Recommended default on established U24:

- run complete focused sets accumulated across the batch;
- run host-sensitive checks affected by the batch;
- optionally skip full `just check` locally and let CI be the complete regression gate.

Require complete local `just check` when the batch changes:

- storage/restore/WAL/file handling;
- migrations/Alembic packaging;
- installed wheel/runtime;
- host/platform behavior;
- test/verification framework itself;
- CI itself;
- environment-sensitive subprocess behavior.

For ordinary domain/web/agent/search changes, CI is a sufficient complete regression environment if the focused local verification is green.

### Tier 4 — CI merge gate

CI remains authoritative full regression before merge.

Run:

- full pytest;
- coverage;
- migration-check;
- scenario evaluation;
- retrieval evaluation.

A merge is forbidden until the final cumulative batch head is green.

This is where repository-wide regression protection belongs.

## Remove redundant canonical entries

### `provider-contract`

Current `just provider-contract` runs:

- `tests/test_provider.py`;
- `tests/test_model_probe.py`.

Both already run inside the full pytest suite.

Therefore it is redundant as an additional universal canonical command.

Proposal:

- remove it from the universal canonical set;
- keep the recipe;
- run it as a focused check when provider/model/tool schema code changes;
- full CI pytest continues to cover these tests for every integration PR.

No coverage is lost.

### `corpus-check` and `scenario-check`

These checks are fast, so removing them yields little wall-clock benefit.

`scenario-eval` already loads/validates both corpus and scenario suite compatibility and executes all selected scenarios.

Recommendation:

- keep the cheap structure checks in CI because their cost is negligible and error messages are clearer;
- do not require them separately at every local task checkpoint;
- run them locally only when corpus/scenario files change.

This simplifies the local lifecycle without weakening CI.

## Coverage policy

Coverage currently dominates CI pytest cost and is report-only.

Two acceptable options:

### Conservative option

Keep coverage on every integrated batch PR.

Because integrated-batch mode reduces five PRs to one, coverage cost is already reduced approximately fivefold per batch.

This is the preferred first optimization.

### Later optional optimization

If CI remains a bottleneck after integrated batches:

- normal PR: plain pytest;
- scheduled/main/final-release CI: pytest with coverage.

Do not make this change initially. It removes little complexity benefit once PR count is reduced, and current coverage history is still young.

## CI parallelism

Current CI spends approximately:

- ~179s full pytest+coverage;
- ~10.5s scenario-eval;
- ~1.1s retrieval-eval.

Parallelizing scenario/retrieval would save at most around 12 seconds, while complicating logs/state.

Recommendation: do not optimize this yet.

The useful optimization target is the number of complete pytest runs, not the small evaluators.

## Correction-loop policy

Current agents often repeat broad verification after each correction.

Proposed rule:

### Before PR

After a focused failure:

- rerun only the failed test/check;
- after correction is stable, rerun the task's full focused set;
- do not restart full repository verification until final batch verification.

### After CI failure

If CI exposes a defect:

1. reproduce with the narrowest local failing check;
2. fix;
3. rerun the narrow check;
4. rerun affected focused set;
5. push;
6. let CI perform the full regression again.

Do not automatically run the entire local canonical suite before every CI retry unless the fix touches a host-sensitive/high-risk area.

CI itself is already about to perform that proof.

## Review/documentation simplification

For integrated batches, replace five mostly repetitive review files with one:

`agent-tasks/reviews/<batch>-r1.md`

containing a section per assignment:

- exact issued spec;
- task commit range;
- focused verification;
- corrections;
- deviations.

Then one final section records:

- cumulative diff self-review;
- final local integration verification;
- PR;
- final CI;
- merge SHA.

This reduces documentation/tool overhead while preserving auditability.

Individual assignment specs remain immutable.

## Seed strategy

Do not create five separate feature branches for an integrated batch.

Use:

- immutable batch control commit;
- one batch implementation branch;
- explicit task boundary commits/checkpoints.

Each task begins only after the previous task's focused checkpoint is green.

The task spec bytes remain immutable at the control SHA.

This preserves scope evidence without branch/PR churn.

## Failure semantics

If task N fails inside an integrated batch:

- stop;
- do not merge partial batch by default;
- report completed task checkpoints and the blocker;
- orchestration decides whether to split accepted earlier tasks into a smaller PR.

No already-green partial work is silently published merely to keep the pipeline moving.

This is slightly more conservative than current serial merge behavior.

## Expected speed improvement

For a five-task batch similar to recent work:

### Current model

Approximately:

- 5 full local suites;
- 5 full CI suites;
- focused tests for each task.

With a ~3.5 minute CI and a comparable multi-minute local full regression, verification alone can easily consume 30+ minutes of machine time plus queue/agent orchestration.

### Integrated model

Approximately:

- focused verification after each of 5 tasks;
- zero or one full local suite depending on risk;
- one full CI suite.

Expected reduction in repeated repository-wide verification: roughly 70–90% for a five-task batch.

The exact end-to-end reduction depends on implementation time and CI queueing, but this attacks the dominant duplicated cost.

## Recommended new protocol behavior

A future v8 should have two modes:

### `verification_mode: isolated`

Current behavior:

- one branch/PR/CI per task;
- full local verification per task.

Use for risky/independent tasks.

### `verification_mode: integrated-batch`

Fast default for pre-approved coherent batches:

- one implementation branch;
- focused checkpoint per task;
- one cumulative final self-review;
- risk-based final local regression;
- one final PR;
- one full CI;
- one merge.

The launcher/manifest chooses the mode. The implementation agent never upgrades itself to the faster mode.

## First rollout recommendation

Do not rewrite CI substantially at first.

Implement only:

1. integrated-batch branch/PR mode;
2. focused-only per-task checkpoints;
3. risk-based local full suite;
4. remove universal local `provider-contract` duplication;
5. one full existing CI on final cumulative head.

Run one infrastructure/non-semantic batch under this model and compare:

- total agent wall time;
- number of pytest invocations;
- CI correction count;
- defects found only by final CI.

If the final CI repeatedly catches problems that separate full local runs would have caught earlier, tighten the relevant focused checkpoint mapping rather than returning to universal full tests after every task.

## Quality argument

This proposal does not lower the merge gate.

Before any code reaches main, the cumulative final head still receives:

- deterministic focused verification for every task;
- final cumulative self-review;
- full repository pytest;
- migration verification;
- complete scenario evaluation;
- complete retrieval evaluation;
- coverage report;
- successful PR CI.

The removed work is repeated proof of the same revision, not unique coverage.
