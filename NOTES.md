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

Canonical sender: `/home/gpt/.local/bin/notify`.

Editable/test wrapper: `/home/gpt/.local/bin/agent-notify`.

Runtime wrapper for `rdu01`: `/home/rdu01/.local/bin/agent-notify`.

The wrapper returns immediately by submitting a transient `systemd --user`
unit. Do not use ordinary `nohup ... &` from a Codex shell tool for this:
tool-runner cleanup may kill that child when the shell call returns. The transient
worker performs remote usage/ntfy work outside the shell-tool lifecycle and has a
short runtime bound. Network failure must never block agent execution. Dry-run:
`AGENT_NOTIFY_DRY_RUN=1`.

Notification body format is intentionally minimal:

```text
HH:MM
MILESTONE
100-3:51   90-5:2:20
```

The last line means remaining percentage and relative time to reset:
5-hour as `percent-hours:minutes`, weekly as
`percent-days:hours:minutes`. Never show absolute reset time.

Implementation: START, one DONE per meaningful top-level task unit, READY FOR
REVIEW, and STOPPED on a real stop condition.

Review: START REVIEW, REVIEW PASS after the first complete independent pass,
CORRECTIONS DONE when applicable, REVIEW COMPLETE, and STOPPED on a real stop
condition.

Use semantic milestones, not periodic time-based heartbeat spam. Never include
secrets or long logs.
