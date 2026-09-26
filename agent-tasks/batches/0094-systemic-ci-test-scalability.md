# Batch: 0094-systemic-ci-test-scalability

Full local required: `false`

## Objective

Make verification scale with continued MVP development without repeatedly micro-optimizing
individual tests whenever ordinary CI crosses a wall-time threshold.

This is a parallel engineering-improvement stream. It must not block batch 0093 or
production MVP activation.

The desired architecture is two-tier verification:

1. ordinary PR/main verification: fast, meaningful, development-feedback oriented;
2. deep verification: complete suite, branch coverage gate, expensive process/package/
   evaluation checks, manually dispatchable by immutable SHA and scheduled regularly.

The solution should improve architecture and scheduling, not merely shave seconds from
individual tests.

## Starting evidence

Current accepted integration tree before this batch includes PR #89 and PR #90.

Observed on final integrated main SHA
`96cffb2a72d3450cf6f5357509d05dee105fcf13`:

- ordinary application-ci #499: success;
- verify job wall about 157 s;
- fast-test step about 138 s;
- pytest: 689 passed / 45 deselected in 133.72 s;
- branch coverage: 83.45%.

Manual extended workflow #1 on the same immutable SHA:

- exact target-SHA binding passed;
- 734 passed;
- branch coverage 83.75%;
- full scenario evaluation and retrieval evaluation green.

A local U24 serial run of the same fast selection without coverage was still about
174 s. Therefore coverage is not the only scaling problem.

A short orchestrator experiment showed that newly added deployment suites contain
subprocess/process-level cost, but the project explicitly does not want recurring
per-test micro-optimization as the primary strategy.

An abandoned experiment branch
`integration/0091-0092-ci-runtime` is tree-equivalent to the accepted main and is
not implementation authority. Do not base work on its experimental commits.

No valid xdist result has been accepted yet.

## Scope

Allowed:

- GitHub Actions workflow architecture;
- Makefile verification entrypoints;
- pytest execution topology;
- test-only dependencies such as parallel execution/coverage tooling when justified;
- deterministic test sharding/parallelism;
- deep/manual/scheduled verification policy;
- structural guardrail tests for CI behavior;
- verification documentation.

Do not change product/runtime semantics.

## Work

1. Define ordinary vs deep verification contract
   - Ordinary PR/main CI must remain a meaningful regression gate and should target
     <=120 s wall time under normal GitHub-hosted conditions.
   - Do not keep branch coverage in ordinary CI merely because it historically lived
     there if moving it materially improves feedback time.
   - Ordinary CI must still run the meaningful fast functional suite; do not solve the
     problem by continuously reclassifying newly slow functional tests as extended.
   - Deep verification owns:
     - complete pytest suite;
     - branch coverage >=83.00%;
     - expensive process/deployment/package checks;
     - full scenario evaluation;
     - retrieval/migration/corpus checks where appropriate.
   - Preserve manual immutable-SHA dispatch.

2. Evaluate scalable execution rather than per-test shaving
   - Measure at least:
     - ordinary serial pytest without coverage;
     - a parallel pytest strategy (for example pytest-xdist) OR deterministic GitHub
       Actions sharding;
     - setup/collection/worker overhead.
   - Choose the simplest topology that preserves isolation and produces reliable
     failures.
   - Check subprocess, SQLite, filesystem, port/socket, temp-directory and environment
     isolation under parallel execution.
   - Do not assume parallel safety from a green partial run.
   - Prefer automatic load balancing over hand-maintained file buckets if it is stable.

3. Move coverage to deep verification if evidence supports it
   - Branch coverage threshold remains >=83.00%; do not lower it.
   - Coverage must remain authoritative in the deep pipeline.
   - If parallel coverage is used, prove data from all workers is correctly combined.
   - Ordinary CI may omit coverage if deep verification provides a reliable scheduled
     and manual gate.

4. Add scheduled deep verification
   - Keep `workflow_dispatch.inputs.target_sha` for manual exact-SHA verification.
   - Add a daily schedule for the default branch.
   - Scheduled deep verification should avoid an expensive full run when main has not
     changed since the previous relevant deep verification. Implement a robust,
     inspectable freshness/change gate rather than a fragile hidden local cache.
   - The scheduled path must bind and log the exact main SHA it verifies.
   - A failure must remain visible/actionable; do not silently suppress failures.
   - Manual dispatch must always run for the requested SHA regardless of daily-change
     optimization.

5. Keep expensive verification complete
   - Deep CI must still exercise every meaningful test currently represented by the
     full suite.
   - Package/wheel, process/SIGKILL, deployment/recovery and scenario evaluation checks
     must not disappear.
   - If markers are reorganized, classify tests by semantic role/cost category, not by
     arbitrary current runtime alone.

6. Guardrails and documentation
   - Structural tests must prove:
     - ordinary CI does not accidentally invoke full/deep coverage;
     - deep manual dispatch accepts immutable target SHA;
     - scheduled deep verification binds to the intended main SHA;
     - coverage threshold remains >=83.00%;
     - full suite remains present in deep verification;
     - no push/PR trigger accidentally runs the full deep workload unless explicitly
       intended.
   - Document the ordinary/deep contract and how to diagnose a scheduled deep failure.

## Acceptance

Evidence must include:

- exact ordinary CI timings on at least two hosted runs of the same final head or an
  equivalent variance-aware sample;
- ordinary test counts and selection;
- deep test count;
- deep branch coverage >=83.00%;
- manual exact-SHA deep run green;
- scheduled-path logic tested without waiting for the real clock;
- proof that parallel/sharded execution, if adopted, does not introduce flaky shared
  state or lost coverage.

Do not claim deterministic <=120 s if hosted-runner variance contradicts it. Report
job wall, test-step wall and pytest duration separately.

## Final verification

```bash
make compile
git diff --check
```

Run the focused CI-structure tests, the ordinary verification entrypoint, and the
complete deep verification entrypoint appropriate to the implementation.

Exact-head GitHub Actions evidence is required.

## Non-goals / stop conditions

- No product-code behavior changes.
- No weakening of coverage threshold.
- No repeated hand-tuning of individual tests as the main strategy.
- No moving tests to deep solely because one hosted runner was slow.
- No provider/Telegram production activation work; that belongs to 0093.
- Do not block or modify the 0093 production activation branch.

## Handoff

Implementer stops at:

`READY FOR REVIEW`

Final handoff must include:

- implementation head SHA;
- chosen CI topology and rationale;
- ordinary hosted timing evidence;
- deep manual exact-SHA evidence;
- scheduled-change-gate evidence;
- test counts and branch coverage;
- known parallelism/flakiness limitations.

Reviewer is an independent role. Review the exact implementation head without reading
the implementer's self-review, handoff, conclusions or remaining-risk list.
The reviewer may append correction commits to the same PR/branch only for independently
established findings, according to `agent-tasks/common/v9.md`.

Neither implementer nor reviewer merges.
