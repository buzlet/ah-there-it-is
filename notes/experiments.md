# Experiments log

This file records experiments performed while developing or operating the project,
including unsuccessful attempts and negative results.

The purpose is reproducibility and institutional memory, not polished documentation.

## Recording rules

For each meaningful experiment, record:

- date and short title;
- status: planned | running | completed | inconclusive | abandoned;
- question / hypothesis;
- exact environment or relevant commit/SHA;
- setup and important inputs;
- commands or procedure sufficient to reproduce it;
- observed result;
- interpretation / conclusion;
- limitations or uncertainty;
- follow-up action, if any.

Do not record secrets, production tokens, private runtime data, or credentials.

Negative results are valuable. Do not delete an experiment merely because it failed.
If a later experiment supersedes it, link the newer entry and mark the older one as
superseded.

Experiments in this branch do not become implementation requirements automatically.
A result that should affect the product or process must be promoted through the normal
design/planning/task flow.

## Entry template

### YYYY-MM-DD — Short experiment title

Status: completed

Question:
What are we trying to learn?

Context:
Relevant repository SHA, branch, host/executor, versions, and constraints.

Procedure:
1. ...
2. ...

Observed result:
- ...

Conclusion:
- ...

Limitations:
- ...

Follow-up:
- ...

---


### 2026-09-26 — GitHub-hosted CI variance for the 0092 fast suite

Status: completed

Question:
Can the optimized ordinary 0092 fast suite be treated as reliably <=120 seconds on GitHub-hosted Ubuntu runners, and how much runner variance exists for an unchanged workload?

Context:
- Repository: `buzlet/ah-there-it-is`
- PR: #90
- Fast selection: 627 passed / 45 extended-deselected tests
- Branch coverage gate: >=83%
- Implementation head: `0ce4c688ee1f35e47f18e69c8fd33da0653154ce`
- Correction head: `b2b0c52b29a5cf610a43c095b1e44f2ab0f8d21b`
- Correction changed only workflow identity/guardrails/review history; test composition and ordinary CI workload were unchanged.

Procedure:
1. Run ordinary `application-ci` on the implementation head.
2. Rerun the same exact implementation head without changing test composition.
3. Run ordinary `application-ci` on the correction head.
4. Explicitly rerun that exact correction head.
5. Compare GitHub job wall time, fast-coverage step wall time, pytest duration, test count, and coverage.

Observed result:
- Implementation head run #494 attempt 1: verify job ~100 s; fast coverage step ~84 s; pytest 81.53 s; coverage 83.84%.
- Same implementation workload rerun: verify job ~71 s; fast coverage step ~57 s.
- Correction head run #496 attempt 1: verify job 128 s; fast coverage step 107 s; pytest 104.15 s; coverage 83.84%.
- Correction head run #496 attempt 2: verify job 123 s; fast coverage step 103 s; pytest 98.73 s; coverage 83.78%.
- Test selection remained 627 passed / 45 deselected.
- Local/sandbox final fast profile for the same selection was about 54–56 s under branch coverage.

Conclusion:
- The deterministic workload was reduced substantially from the original ~5 minute CI baseline.
- Hosted-runner CPU/runtime variance is large enough that the same test composition ranged from roughly 71 to 128 seconds at the job level.
- A strict <=120 s observation cannot be guaranteed from this sample without either further deterministic reduction or weakening/moving additional verification.
- Batch 0092's explicit runner-variance escape clause is therefore relevant: report the measured breakdown rather than hiding over-target hosted runs.

Limitations:
- Small hosted-runner sample.
- No controlled runner hardware allocation; GitHub-hosted capacity/noise is external.
- Future test additions, including deployment/recovery tests from PR #89, can change the combined fast-gate runtime after integration.

Follow-up:
- After PR #89 and PR #90 are both integrated, measure ordinary CI again on the combined main tree.
- If the combined deterministic workload materially increases or ordinary hosted CI routinely exceeds two minutes, profile the new hotspots before moving any additional meaningful tests to extended verification.


### 2026-09-26 — Production-mode fail-closed systemd preflight

Status: completed

Question:
Can shipped production systemd units reject an absent or non-production environment mode without breaking the convenient development default used by ordinary local CLI execution?

Context:
- PR: #89
- Correction head: `5fa4323af138394ed43614a564b223e85bba2859`
- Production units use `ah-there-it-is schema-check --require-production` in `ExecStartPre`.
- Generic CLI still defaults an unset environment mode to development.

Procedure:
1. Exercise the exact shipped `ExecStartPre` through transient user-systemd units with scratch EnvironmentFiles.
2. Test unset environment mode, unset mode with a prepared relative SQLite DB, explicit development, malformed mode, missing production DB, relative production DB, and valid production with a prepared absolute DB.
3. Verify invalid cases stop before `ExecStart` and do not echo a synthetic secret marker.
4. Reinstall/reload the actual user units, restart web, and verify health; keep Telegram stopped.

Observed result:
- Unset, development, malformed, missing-DB, and relative-production configurations failed before service start.
- Explicit production with a valid absolute prepared SQLite DB passed preflight.
- Synthetic secret marker was absent from output.
- Installed units verified after reload; production web returned health OK.
- Telegram remained stopped with MainPID=0.
- Exact-head application-ci #497 succeeded.

Conclusion:
- A deployment-specific production requirement can be enforced without changing normal local development semantics.
- Keeping the production requirement in shipped service preflight avoids treating a missing environment variable as a valid production configuration.

Follow-up:
- Preserve `--require-production` (or an equivalent deployment-specific invariant) if startup/configuration code is refactored later.


### 2026-09-26 — 0091 + 0092 integration CI regression and compatibility fix

Status: completed

Question:
Would the optimized ordinary CI from batch 0092 remain within its intended ~2 minute envelope after the deployment/recovery test additions from batch 0091 were merged, and if not, could the regression be removed without weakening meaningful coverage?

Context:
- PR #89 merged as `b283a779c9f680b0207f934f12b3a1b68f281d0d`.
- PR #90 merged as `96cffb2a72d3450cf6f5357509d05dee105fcf13`.
- Combined ordinary CI #499 was functionally green but measured 157 s job wall, 138 s fast-coverage step, and 133.72 s pytest for 689 passed / 45 deselected tests at 83.45% branch coverage.
- The final compatibility fix was PR #91, merged as `d04a4e08fe9d51529b5fa1811e49e5290cf6f011`.

Procedure:
1. Profile only the deployment/recovery test files added by PR #89 on an exact detached checkout of `96cffb2...` on U24.
2. Measure `tests/test_startup_preflight.py` separately from the other new deployment/recovery suites.
3. Inspect the slowest test cases.
4. Replace only the redundant malformed-environment Cartesian subprocess matrix (5 malformed values × 5 real CLI entrypoints) with pairwise factor coverage: every malformed value and every real entrypoint still appears once.
5. Run the focused startup-preflight suite locally.
6. Verify PR #91 with GitHub-hosted ordinary CI.
7. Merge PR #91 and run ordinary CI twice on the exact final main SHA.
8. Dispatch manual extended CI with `target_sha` equal to that same final main SHA.

Observed result:
- U24 profiling before the fix: startup-preflight file 29.08 s; the other five new deployment/recovery suites together 11.70 s.
- U24 startup-preflight after the pairwise matrix change: 14.60 s, green.
- PR #91 exact-head CI #500: 110 s verify job, 94 s fast step, 669 passed / 45 deselected in 91.48 s, 83.51% coverage, green.
- Final main SHA: `d04a4e08fe9d51529b5fa1811e49e5290cf6f011`.
- Final ordinary CI #501 attempt 1: 149 s verify job; pytest 669 passed / 45 deselected in 122.81 s; 83.45% coverage; green.
- Exact same final SHA #501 attempt 2: 81 s verify job; fast step 69 s; pytest 669 passed / 45 deselected in 66.29 s; 83.51% coverage; green.
- Final manual extended run #2 checked out and logged exact SHA `d04a4e08fe9d51529b5fa1811e49e5290cf6f011`.
- Extended result: 714 passed in 216.94 s, 83.75% branch coverage, migration/corpus/scenario checks green, full scenario evaluation green, retrieval evaluation 86/86 green.

Conclusion:
- The integration initially introduced a real deterministic CI regression, mainly from a redundant 25-process configuration-validation test matrix.
- Removing only that redundancy restored the ordinary workload without moving meaningful deployment/recovery tests to extended verification.
- GitHub-hosted runner variance remains very large: the identical final tree produced 149 s and 81 s ordinary verify jobs. Timing should therefore be tracked with deterministic workload profiling plus multiple hosted observations rather than a single run.
- Functional integration of batches 0091 and 0092 is green on the final immutable main SHA, including the full extended gate.

Limitations:
- Hosted-runner timing remains externally noisy and cannot guarantee a hard wall-time bound for every run.
- The compatibility change preserves factor coverage rather than every Cartesian combination; this is appropriate because environment validation occurs before command-specific dispatch.

Follow-up:
- Keep monitoring ordinary CI timing as the suite grows.
- Profile newly added subprocess-heavy tests before expanding the extended set or weakening fast-gate coverage.


### 2026-09-26 — Post-0091/0092 integrated CI scaling observation

Status: completed

Question:
What happens to the optimized ordinary CI after the deployment/recovery tests from 0091 are integrated, and should the project continue tuning individual tests to hold a fixed wall-time target?

Context:
- Final integrated main after PR #89 and PR #90: `96cffb2a72d3450cf6f5357509d05dee105fcf13`.
- Ordinary application-ci run #499 was the first fast-gate run over the combined tree.
- Manual application-extended-ci run #1 targeted the same immutable SHA.

Observed result:
- Ordinary CI #499: green; verify job about 157 s; fast-test step about 138 s; pytest 689 passed / 45 deselected in 133.72 s; branch coverage 83.45%.
- Manual extended CI #1: exact-SHA bind green; 734 passed; branch coverage 83.75%; full scenario and retrieval evaluation green.
- U24 serial fast selection without coverage was still about 174 s, showing that coverage is not the only scaling cost.
- A short experiment identified duplicated subprocess cost in production-preflight tests, but the resulting micro-optimization direction was explicitly rejected as the primary long-term strategy.
- Experimental branch `integration/0091-0092-ci-runtime` was restored to a tree identical to accepted main; its experimental commits remain history only and are not implementation authority.

Conclusion:
- Repeated per-test shaving or moving newly slow tests to extended is not a sustainable CI architecture as the MVP grows.
- Future optimization should treat ordinary and deep verification as separate tiers and evaluate scalable parallel/sharded execution.
- Coverage and expensive full verification are candidates for the deep tier with manual exact-SHA dispatch plus scheduled execution when main changed.
- Production MVP activation is the primary project stream; CI/test scalability is parallel improvement work and must not block launch.

Follow-up:
- Primary batch: `0093-production-mvp-activation`.
- Parallel engineering batch: `0094-systemic-ci-test-scalability`.
