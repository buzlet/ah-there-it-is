# Project notes

## Backlog / issue clustering rule

When new product observations, defects, UX wishes, or follow-up ideas appear:

1. Classify the observation into a stable product cluster before creating an issue.
2. Search the existing open issues in that cluster first.
3. Prefer updating and expanding an existing issue when the new observation is part of the same problem boundary.
4. Create a new issue only when the observation has a distinct implementation or verification boundary.
5. Prefix issue titles with the cluster name, for example:
   - `[Russian semantics] ...`
   - `[Telegram UX] ...`
6. Cross-link related issues inside the cluster and explicitly document boundaries between them so work is not duplicated.
7. Keep semantic/data correctness separate from presentation/transport UX even when one user-visible example exposes both.
8. When a concrete production conversation exposes a defect, preserve that example in the relevant issue and turn it into deterministic regression coverage.
9. New requirements should be merged into the appropriate existing cluster issues rather than accumulated only in chat.
10. Before issuing an implementation batch, review the whole relevant cluster and decide whether issues should be implemented together or as separate batches.

Current clusters introduced from production Telegram testing:

- **Russian semantics / canonical inventory structure**
  - #97 relational location hierarchy
  - #98 canonical item/location naming
  - #99 semantic entity matching and specificity
- **Telegram presentation / mobile navigation**
  - #100 compact rendering, native formatting, approximate quantity display, drill-down navigation, and paging
- **Configuration / operator policy / future user preferences**
  - #101 configuration classification, layering, hard-coded-setting audit, and future per-user override candidates


## Configuration classification note

When deciding whether a hard-coded value should move into configuration, distinguish at least:

- domain invariants;
- protocol/API constants;
- deployment/operator settings;
- secrets/credentials;
- product defaults / UX tuning;
- future user preferences;
- internal implementation constants.

A future user-preference layer is a design concern even while the current product remains single-user. The audit should mark which values may later support per-user overrides and who is allowed to change them, but must not weaken correctness/safety invariants or prematurely implement multi-user support.

Configuration precedence, when applicable, should be explicit. A candidate model is:

`product default -> deployment/operator override -> future user override`

Secrets remain a separate channel, and domain invariants are not overrideable configuration.


## U24 agent notification rule

U24 agents use the host-local helper:

`/home/rdu01/.local/bin/notify`

Notifications are best-effort and must be invoked with `|| true`.

Implementation agents notify:
- START after executor/branch/issuance validation;
- TASK DONE after each meaningful top-level batch work unit is complete;
- READY FOR REVIEW at the final implementation stop;
- STOPPED on an abnormal stop condition when possible.

Reviewers notify:
- START REVIEW after exact-head/scope validation;
- REVIEW PASS after one complete independent review pass, reporting CLEAN or a concise finding count/category;
- CORRECTIONS DONE only if corrections were required, after focused correction verification and before final exact-head verification;
- REVIEW COMPLETE with CLEAN/CORRECTED, final head, and CI state when known;
- STOPPED on an abnormal stop condition when possible.

Do not use time-based notification spam as a substitute for semantic milestones.
Do not include secrets or long logs.
