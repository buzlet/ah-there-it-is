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
