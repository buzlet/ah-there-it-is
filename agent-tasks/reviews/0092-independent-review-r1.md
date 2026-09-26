# 0092 test/CI optimization — independent review r1

**Agent effort: 3/5**

Implementation reviewed: `0ce4c688ee1f35e47f18e69c8fd33da0653154ce`  
Issuance: `f9b0c3e3a2776ffced38307f99bd55c3b5b18a58`  
Branch: `work/0092-test-ci-optimization`  
PR: #90

## Accepted implementation

The main optimization is accepted. Do not rework without necessity:

- ordinary fast suite;
- explicit extended suite;
- session-level immutable 1000-item SQLite template + isolated clones;
- removal of unnecessary real sleeps;
- reduced synthetic volumes where tested boundaries remain equivalent;
- `extended` marker;
- `test-fast`, `test-profile`, `test-extended`;
- branch coverage threshold 83%;
- sandbox inclusion of `agent-tasks/executors/`;
- no product-code/dependency changes.

The ordinary CI reduction from roughly 5–6 minutes to about 100 seconds is considered correct.

## Correction 1 — make extended CI target an explicit immutable SHA

Current `application-extended-ci` uses plain `workflow_dispatch` and checks out `${{ github.sha }}`. This is only unambiguous relative to the ref used for dispatch and is insufficient after merge/branch movement or deletion.

Required:

```yaml
workflow_dispatch:
  inputs:
    target_sha:
      description: Exact commit SHA to verify
      required: true
      type: string
```

The extended job must checkout the explicit SHA:

```yaml
- uses: actions/checkout@v4
  with:
    ref: ${{ inputs.target_sha }}
```

and independently assert:

```bash
test "$(git rev-parse HEAD)" = "${{ inputs.target_sha }}"
```

It must also log the tested SHA. Do not rely on branch tip identity.

Guardrail tests must verify at minimum:

- extended workflow remains `workflow_dispatch` only;
- `target_sha` is required;
- checkout uses explicit `target_sha`;
- `git rev-parse HEAD == target_sha` is asserted;
- ordinary CI does not invoke the extended plan.

Do not make extended automatic on push/PR/nightly.

## Correction 2 — verify hosted-runner timing is not a one-off fast run

Batch 0092 requires not claiming success from one unusually fast runner. The final workload at `0ce4c688...` has only one final GitHub-hosted timing result.

After correction commit:

1. wait for ordinary `application-ci` on the exact correction head;
2. record verify job wall time, Fast tests with coverage step time, passed/deselected counts, and branch coverage;
3. rerun the same exact-head ordinary workflow once more if GitHub API permits;
4. compare both hosted-runner results.

If rerun is unavailable, record the limitation and leave an explicit orchestrator follow-up. If the second run materially exceeds 120 s, report and analyze variance rather than hiding it. Do not move additional meaningful tests to extended merely for a few seconds without profiling.

## Correction 3 — normalize timing language in PR self-review

Use GitHub Actions job `started_at → completed_at` as the primary job wall-time metric. For the previous final run this is approximately 100 s, not 96.5 s. Step duration and pytest-reported duration may be reported separately.

## Required correction verification

Before publication:

```bash
make compile
git diff --check
make test-fast
pytest tests/test_ci_structure.py
```

Run `make test-fast-coverage` if it does not unnecessarily duplicate already completed full-local verification.

A repeat full extended suite is desirable but not required when corrections are limited to workflow/CI-structure tests.

## Extended workflow execution constraint

After the workflow with `target_sha` exists on the default branch, the orchestrator must be able to dispatch `application-extended-ci` with an explicit immutable SHA. If GitHub does not permit dispatch before the workflow reaches the default branch, prove workflow structure by tests and retain local full-suite evidence.

Do not publish the workflow onto `main` before PR merge merely to bypass this platform limitation.

## Scope restrictions

Do not change:

- product semantics;
- `src/`;
- dependency set;
- coverage threshold;
- fast/extended composition without new measured basis;
- live provider/Telegram behavior.

Do not add unrelated linting/tooling.

Correction publication must remain append-only on PR #90 / `work/0092-test-ci-optimization`, without amend/rebase/squash/force-push/merge.
