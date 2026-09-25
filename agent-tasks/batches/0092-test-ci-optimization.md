# Batch: 0092-test-ci-optimization

Full local required: `false`

## Objective

Reduce ordinary PR/main GitHub Actions verification to a practical **1–2 minute
maximum target** without weakening core correctness checks.

Investigate and optimize the **tests themselves** as well as workflow structure.
Long-running verification that is valuable but unsuitable for every PR/push must
remain available through an explicit on-demand extended verification plan.

This batch is performance/verification infrastructure work, not product work.

## Acceptance targets

For ordinary `application-ci` on a normal GitHub-hosted Ubuntu runner:

- target total `verify` job wall time: **<= 120 seconds**;
- design the deterministic test portion with enough margin that ordinary runner
  variance does not normally push the job beyond two minutes;
- `sandbox-bundle` remains parallel and lightweight.

Do not claim success from one unusually fast runner. Compare timings against the
recent ~5 minute test baseline and record step/test timing evidence.

The exact threshold is an engineering target rather than permission to delete
meaningful verification. If a hard external runner variance prevents a strict
two-minute observation after deterministic work is reduced appropriately, report
the measured deterministic/runtime breakdown instead of hiding it.

## Work

1. Establish a timing baseline before optimization.
   - Measure the current ordinary CI step durations.
   - Profile pytest itself using built-in duration reporting (for example
     `pytest --durations`) without adding a profiling dependency.
   - Identify the slowest individual tests, test modules and shared fixtures.
   - Measure coverage overhead separately where useful.
   - Record enough baseline evidence in the PR self-review to show where time was
     actually spent.

2. Audit the test suite itself.
   Investigate at least:
   - repeated database/schema creation and Alembic/migration setup;
   - fixture scopes and unnecessary recreation of expensive state;
   - repeated app/client/runtime construction;
   - real sleeps, retry/backoff waits and timeout-based synchronization;
   - subprocess/process startup;
   - filesystem-heavy setup/copies;
   - redundant end-to-end paths already covered more cheaply elsewhere;
   - expensive parametrization or scenario duplication;
   - tests whose isolation strategy can be made cheaper without sharing mutable
     state;
   - serial work that can safely be avoided, cached or represented by a prepared
     immutable fixture/template.

   Optimize demonstrated hotspots. Preserve assertions, isolation and defect
   detection. Do not merely mark every slow test as extended.

3. Prefer structural test-speed fixes.
   Examples when justified by measurements:
   - replace real waiting with deterministic clocks/events/fakes where the
     existing architecture supports it;
   - reuse immutable setup at module/session scope while giving each test isolated
     mutable state;
   - build expensive schema/reference fixtures once and cheaply clone/reset them;
   - avoid redundant migration/startup work inside tests that are not testing
     migration/startup;
   - remove duplicate verification only when equivalence is demonstrated.

   Minimal production test seams are allowed only when they improve deterministic
   testing without changing product semantics or weakening runtime behavior.

4. Define a fast ordinary verification plan.
   - Add clear Make entrypoints such as `test-fast` / `test-profile` if useful.
   - The ordinary automatic PR/main workflow must retain the high-value correctness
     gate: compilation plus the fast test set and other cheap checks that catch
     normal regressions.
   - Keep critical transaction/idempotency/security/storage/runtime invariants in
     the ordinary gate even if they require optimization.
   - Do not lower the existing full-suite coverage requirement of 83%.
   - Prefer keeping the ordinary fast-gate coverage meaningful and close to the
     existing threshold. Any separate fast-gate threshold must be explicitly
     justified by which extended tests are excluded; do not silently trade
     coverage for speed.

5. Create an explicit extended verification plan for genuinely expensive checks.
   - Extended verification must contain every meaningful check/test removed from
     the ordinary gate.
   - Preserve the full-suite branch coverage threshold at **>= 83%**.
   - Include any expensive integration/migration/recovery/evaluation checks whose
     cost is not justified on every ordinary PR.
   - Provide a clear Make entrypoint such as `test-extended` or equivalent.
   - Add a dedicated GitHub Actions workflow or clearly separated job that runs
     **only on explicit request**, not on every push/PR.
   - Prefer `workflow_dispatch` and/or an explicit PR label event such as
     `extended-ci`; do not add a nightly/periodic run unless a measured need is
     demonstrated.
   - The workflow must make the exact tested SHA unambiguous.

6. Fix workflow inefficiencies.
   Inspect:
   - dependency install/cache behavior;
   - duplicate setup across jobs;
   - coverage invocation cost;
   - repeated evaluation commands;
   - artifact creation/compression;
   - opportunities for safe parallelism;
   - unnecessary workflow triggers.

   Do not optimize a 1–10 second step while leaving multi-minute test hotspots
   unexplained.

7. Fix v9 sandbox artifact completeness.
   The current sandbox bundle copies common/design/planning/batches/assignments/
   reviews but omits `agent-tasks/executors/`.

   v9 agents must be able to recover the selected executor profile from the
   issuance source. Add `agent-tasks/executors/` to the sandbox artifact and
   verify the bundled path is present.

8. Add regression/guardrails for CI structure where practical.
   - Keep workflow syntax valid.
   - Ensure ordinary CI cannot accidentally start the extended suite on every
     push/PR.
   - Ensure the extended plan is discoverable and explicit.
   - Make test selection deterministic and documented in Make/workflow code, not
     dependent on ad-hoc shell exclusion lists hidden in CI.

## Required measurement evidence

Before handoff report:

- baseline ordinary CI/test duration;
- optimized local fast-suite duration in the sandbox;
- exact-head GitHub ordinary CI duration;
- slowest tests/modules before and after;
- which checks remain automatic;
- which checks moved to extended verification and why;
- full/extended verification result from this optimization work.

Use at least one complete extended/full-suite run during this batch to prove that
no verification was lost. If a single sandbox invocation exceeds the executor
ceiling, deterministic shards covering the complete suite are acceptable; record
the exact shard coverage.

## Final verification

Before PR:

```bash
make compile
git diff --check
```

Run the optimized ordinary fast plan locally.

Run the complete extended/full test plan once during the batch.

On the exact PR head:

- ordinary `application-ci` must be green;
- collect its actual durations and evaluate the <=120 second target;
- exercise the explicit extended verification trigger once for this optimization
  batch when the workflow mechanism permits it on the PR head; otherwise provide
  the complete sandbox full-suite evidence and make the post-merge explicit
  extended run a required orchestrator follow-up.

## Non-goals / stop conditions

- Do not change product semantics.
- Do not delete meaningful regression coverage just to meet the timer.
- Do not hide slow tests behind `skip`, `xfail` or broad exclusions.
- Do not lower the full-suite 83% coverage requirement.
- Do not add a test parallelization dependency before measurements show it is
  necessary; prefer removing avoidable work first.
- Do not make extended verification automatic on every PR/push.
- Do not add unrelated linting/tooling.
- Do not use live provider or Telegram calls.
- Stop/report if meeting the target would require weakening a critical invariant
  rather than optimizing/splitting verification honestly.

## Handoff

Implementer stops at:

`READY FOR REVIEW`

Independent review follows `agent-tasks/common/v9.md`.

Neither implementer nor reviewer merges.
