# Core MVP task registry after reviewed 0084–0090

Status: implementation/review work through 0090 is complete and merged.

## Completed

- 0061–0070 — quantity / removed / portable-v3 / immediate Undo.
- 0071–0080 — Item media references + single-user/private-text Telegram adapter.
- 0081–0083 — provider/model benchmark campaign, comparison and promotion evidence.
- PR #84 — independent media/Telegram corrections.
- PR #83 — independent model-evaluation corrections.
- 0084–0090 — final integrated MVP correctness/hardening.
- PR #87 — implementation of 0084–0090.
- PR #88 — independent review corrections for 0084–0090, integrated into PR #87 before final merge.

Historical specs are archived and are not active implementation authority.

## Next Direct batch: 0091+

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

0084–0090 completed under v8. New work is issued under v9.

For batches issued after v9 is adopted:

implementation → PR self-review → exact-head CI green → READY FOR REVIEW

Then an independent reviewer receives the exact implementation head and reviews
the code/tests without reading the implementer's self-review, handoff, conclusions
or remaining-risk list. If corrections are needed, the reviewer appends correction
commits to that same implementation branch/PR and obtains new exact-head CI.

Implementer and reviewer do not merge. The orchestrator verifies the final
review range/current-main compatibility and performs integration.
