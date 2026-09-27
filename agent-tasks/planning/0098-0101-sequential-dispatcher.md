# Dispatcher plan: 0098 + 0100 + 0101

## Role

Act only as a sequential Codex dispatcher/orchestrator on U24.

Model for this dispatcher: `gpt-6-luna`, reasoning `max`.

Do not implement product changes yourself. Your job is to bootstrap the issued
workdirs, launch exactly one nested Codex at a time, monitor it, validate its
terminal marker/head, then launch the next nested Codex.

Never have more than one nested implementation/review Codex process running at
once.

Do not merge any PR/branch and do not deploy production.

Use:

- executor: `agent-tasks/executors/u24-direct-shell.md`
- protocol: `agent-tasks/common/v9.md`
- user: `rdu01`
- nested Codex sandbox: `danger-full-access`

Use the U24 notification wrapper for dispatcher milestones:

`/home/rdu01/.local/bin/agent-notify`

Keep dispatcher notifications compact.

## Queue

### Cluster A — configuration architecture/audit

Task:
`agent-tasks/batches/0098-configuration-boundary-audit.md`

Issuance:
`d896ad3a9894cb3a706c9ce3087d6922f11ee93b`

Branch:
`work/0098-configuration-boundary-audit`

Workdir:
`/home/rdu01/projects/0098-configuration-boundary-audit`

Implementation:
- model: `gpt-6-luna`
- reasoning: `max`

Review+correction:
- model: `gpt-6-astra`
- reasoning: `medium`

### Cluster B — Russian semantics

Task:
`agent-tasks/batches/0100-russian-semantics-canonical-hierarchy-identity.md`

Issuance:
`efc0bc3fb7d44ebd42dd925da48cb393c23ba7c0`

Branch:
`work/0100-russian-semantics-canonical-hierarchy-identity`

Workdir:
`/home/rdu01/projects/0100-russian-semantics-canonical-hierarchy-identity`

Implementation:
- model: `gpt-6-luna`
- reasoning: `max`

Review+correction:
- model: `gpt-6-astra`
- reasoning: `medium`

### Cluster C — Telegram native UX/runtime

Task:
`agent-tasks/batches/0101-telegram-native-ux-navigation-progress-failures.md`

Issuance:
`8f9300cca27890c717fb8c223ccf31a4d7bf780e`

Branch:
`work/0101-telegram-native-ux-navigation-progress-failures`

Workdir:
`/home/rdu01/projects/0101-telegram-native-ux-navigation-progress-failures`

Implementation:
- model: `gpt-6-luna`
- reasoning: `max`

Review+correction:
- model: `gpt-6-astra`
- reasoning: `medium`

## Required execution order

Run every implementation first, one at a time:

1. implementation 0098
2. implementation 0100
3. implementation 0101

Only after all three implementation agents have successfully ended with
`READY FOR REVIEW`, start the review phase:

4. review+correction 0098
5. review+correction 0100
6. review+correction 0101

Do not overlap stages.

## Bootstrap

For each cluster before implementation:

1. if the workdir does not exist, clone the repository there and checkout the
   pre-created work branch;
2. verify:
   - `id -un == rdu01`
   - `HOME == /home/rdu01`
   - workdir is exact;
   - current branch is exact;
   - `git rev-parse HEAD` equals issuance before implementation starts;
3. do not merge/rebase current main into the work branch.

If an existing clean checkout is present at the exact branch/issuance, reuse it.

If an existing checkout has unexpected local modifications or wrong branch/head,
stop the queue and report rather than destroying work.

## Nested implementation prompt template

For each implementation launch, construct this prompt with the cluster values:

```text
Work as the implementation+verification agent for buzlet/ah-there-it-is.

Protocol: agent-tasks/common/v9.md
Task: <TASK>
Executor: agent-tasks/executors/u24-direct-shell.md
Issuance: <ISSUANCE>
Branch: <BRANCH>

You are the implementation agent. Model-independent product behavior and all
acceptance criteria come from the issued batch.

Follow protocol v9 exactly.
Follow the U24 executor notification rules exactly.
Use /home/rdu01/.local/bin/agent-notify for START, meaningful DONE milestones,
READY FOR REVIEW, and STOPPED when applicable.

Work only in <WORKDIR>.
Do not merge or deploy production.
Open/update the single implementation PR as required by v9 and wait for
authoritative exact-head CI.
Stop only at READY FOR REVIEW or a real protocol stop condition.
```

Launch with:

```bash
/home/rdu01/.local/bin/codex exec --ephemeral \
  -s danger-full-access \
  -m gpt-6-luna \
  -c 'model_reasoning_effort="max"' \
  "<PROMPT>"
```

Run it detached with stdout/stderr redirected to a durable log under:

`/home/rdu01/.local/state/ah-there-it-is/dispatcher/`

Record PID, task, stage and log path in a small dispatcher state file.

## Monitoring implementation

After launch:

- wait about 150 seconds between checks;
- check whether the PID still exists;
- do not tail continuously or poll every few seconds;
- while running, do nothing except the next scheduled check;
- when it exits, inspect only enough log tail/state to establish terminal status;
- verify the worktree is clean;
- record exact branch HEAD;
- require the nested output to contain `READY FOR REVIEW`;
- verify issuance is an ancestor of final implementation HEAD;
- verify the issued task file did not change in `issuance..HEAD`;
- when practical, verify a PR exists and exact-head CI is green.

If the agent exits without `READY FOR REVIEW`, or leaves a dirty/broken checkout,
send dispatcher STOPPED notification and stop the whole queue.

Do not silently restart a failed agent with a fresh model. Human review is
required for a genuine stop condition.

Store each successful implementation exact head as `I_<batch>`. That exact SHA
is the only review target.

## Nested review+correction prompt template

The reviewer must be independent.

Do NOT provide:
- implementation final handoff;
- implementation conclusions;
- implementation self-review/PR narrative;
- remaining-risk claims from the implementer.

Pass only the v9 review handoff plus role constraints:

```text
Work as the independent review+correction agent for buzlet/ah-there-it-is.

Protocol: agent-tasks/common/v9.md
Task: <TASK>
Executor: agent-tasks/executors/u24-direct-shell.md
Issuance: <ISSUANCE>
Implementation: <I_SHA>
Branch: <BRANCH>

Model: reviewer/correction role.

Reconstruct requirements independently from the issued task, AGENTS.md, protocol,
relevant source/tests and the exact implementation code at <I_SHA>.
Do not read or rely on the implementation PR description/self-review, the
implementer's final handoff, or implementation conclusions before freezing your
own findings.

Perform one full adversarial independent review pass first.
Send START REVIEW at start and REVIEW PASS after that full pass.

If no defect is found:
- run the required verification;
- require authoritative CI for the exact head when applicable;
- finish REVIEW COMPLETE — CLEAN.

If a demonstrated defect is found:
- reproduce it first where practical;
- add a regression test first where practical;
- append the narrowest correction commits to the SAME branch;
- never amend/rebase/squash/force-push;
- do not create a correction branch/PR;
- send CORRECTIONS DONE after focused correction verification;
- run final required checks and authoritative exact-head CI;
- finish REVIEW COMPLETE — CORRECTED.

Follow the issued batch's Independent review emphasis.
Follow the U24 notification protocol.
Do not merge or deploy production.
```

Launch with:

```bash
/home/rdu01/.local/bin/codex exec --ephemeral \
  -s danger-full-access \
  -m gpt-6-astra \
  -c 'model_reasoning_effort="medium"' \
  "<REVIEW_PROMPT>"
```

Before launch, verify the branch is exactly at stored implementation head
`I_<batch>` and the worktree is clean.

## Monitoring review

Use the same approximately 150-second polling cadence.

When a review process exits:

- require terminal marker `REVIEW COMPLETE — CLEAN` or
  `REVIEW COMPLETE — CORRECTED`;
- verify worktree clean;
- record final exact head `R_<batch>`;
- if CLEAN, require `R == I`;
- if CORRECTED, require `I` is an ancestor of `R`;
- verify issuance is an ancestor of `R`;
- verify the issued batch file was not changed;
- verify exact-head CI green when applicable.

On any abnormal exit/failed verification, stop the entire queue and report.

## Dispatcher notifications

Send at minimum:

- `DISPATCH START — 3 clusters`
- one compact message when each implementation starts;
- one compact message when each implementation reaches READY FOR REVIEW;
- `IMPLEMENTATION PHASE COMPLETE — 3/3`
- one compact message when each review starts;
- one compact message when each review completes CLEAN/CORRECTED;
- `DISPATCH COMPLETE — 3 reviewed branches`

All messages go through `agent-notify`, which supplies time and compact limits.

## Final state

Do not merge.

Expected final branches:

- `work/0098-configuration-boundary-audit`
- `work/0100-russian-semantics-canonical-hierarchy-identity`
- `work/0101-telegram-native-ux-navigation-progress-failures`

Each must be at an independently reviewed exact head with CLEAN or CORRECTED
status and authoritative exact-head CI where applicable.

Final dispatcher report must list, for every cluster:

- issuance SHA;
- implementation SHA;
- final reviewed SHA;
- CLEAN/CORRECTED;
- PR number if present;
- exact-head CI state;
- any direct follow-up/blocker.

Also report whether any pair of final branches changed overlapping source files
so the later human integration step can anticipate semantic/Git conflicts.
