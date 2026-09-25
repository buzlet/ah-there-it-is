# Core MVP task registry after reviewed 0071–0083

Status: 0071–0083 implemented, independently reviewed, corrected and merged.

## Completed

- 0061–0070 — quantity / removed / portable-v3 / immediate Undo.
- 0071–0080 — Item media references + single-user/private-text Telegram adapter.
- 0081–0083 — provider/model benchmark campaign, comparison and promotion evidence.
- PR #84 — independent media/Telegram corrections.
- PR #83 — independent model-evaluation corrections.

Historical specs are archived and are not active implementation authority.

## Next sandbox batch: 0084–0090

Purpose: final integrated MVP correctness/hardening only.

The sandbox batch may:
- reproduce suspected defects;
- add adversarial/regression tests;
- make narrow code corrections;
- check cross-surface invariants, crash/idempotency, Undo/lifecycle/media interactions, security/privacy, boundedness, package/startup semantics and integrated MVP acceptance evidence.

The sandbox batch must not:
- add new product features;
- perform target-server preparation;
- configure systemd/services;
- choose production filesystem/env/secrets locations;
- implement deployment scripts tied to the target host;
- rehearse real deployment/restart/backup paths.

## Following Direct batch: 0091+

Purpose: deployment/environment readiness on the actual target server.

The Direct agent owns host-specific MVP preparation after code-level acceptance:
- runtime/service-manager setup;
- environment and secret placement;
- filesystem/data/log paths;
- deployment and restart rehearsal;
- schema/readiness checks against the target installation;
- operational backup/restore path validation where applicable;
- any host-specific issues discovered during deployment preparation.

Direct work must not silently reopen product semantics.

## Review lifecycle

The currently running 0084–0090 batch was issued under v8 and finishes under v8.

For batches issued after v9 is adopted:

implementation → PR self-review → exact-head CI green → READY FOR REVIEW

Then an independent reviewer records the implementation head and reviews the same
PR. If corrections are needed, the reviewer appends correction commits to that
same implementation branch/PR and obtains new exact-head CI.

Implementer and reviewer do not merge. The orchestrator verifies the final
review range/current-main compatibility and performs integration.
