# Native multi-agent dispatcher plan: 0098 + 0100 + 0101

## Purpose

Replace the failed shell-spawn dispatcher with Codex's built-in multi-agent
collaboration tools.

The root dispatcher is one Codex session. It must use native `spawn_agent`,
`wait_agent`, and the corresponding close/list tools exposed by its runtime.
It must never launch another `codex` executable from shell.

## Root runtime

Launch the root dispatcher as:

- model: `gpt-6-luna`;
- reasoning: `max`;
- multi-agent enabled;
- subagent concurrency: exactly 1;
- default subagent model: `gpt-6-luna`;
- default subagent reasoning: `max`.

Recommended CLI configuration:

```bash
codex exec \
  --enable multi_agent \
  -m gpt-6-luna \
  -c 'model_reasoning_effort="max"' \
  -c 'agents.max_concurrent_threads_per_session=1' \
  -c 'agents.default_subagent_model="gpt-6-luna"' \
  -c 'agents.default_subagent_reasoning_effort="max"' \
  ...
```

Do not define/use a custom `agent_type` for this queue. Implementation agents
use the configured Luna/max default. Review agents use explicit per-spawn model
and reasoning overrides.

## Why native spawn is mandatory

A previous dispatcher launched nested Codex CLI processes from its shell tool
with `nohup ... &`. The child disappeared with an empty log after the shell
tool returned even though the identical launcher works from an ordinary host
shell.

Treat background OS descendants created by a Codex shell tool as lifecycle-bound
to that tool invocation. Do not use them for nested agents.

The notification wrapper is separately detached through `systemd --user`; that
is only for short advisory ntfy delivery and is not an agent-launch mechanism.

## Queue

### A — configuration architecture/audit

Task:
`agent-tasks/batches/0098-configuration-boundary-audit.md`

Issuance:
`d896ad3a9894cb3a706c9ce3087d6922f11ee93b`

Branch:
`work/0098-configuration-boundary-audit`

Workdir:
`/home/rdu01/projects/0098-configuration-boundary-audit`

### B — Russian semantics

Task:
`agent-tasks/batches/0100-russian-semantics-canonical-hierarchy-identity.md`

Issuance:
`efc0bc3fb7d44ebd42dd925da48cb393c23ba7c0`

Branch:
`work/0100-russian-semantics-canonical-hierarchy-identity`

Workdir:
`/home/rdu01/projects/0100-russian-semantics-canonical-hierarchy-identity`

### C — Telegram native UX/runtime

Task:
`agent-tasks/batches/0101-telegram-native-ux-navigation-progress-failures.md`

Issuance:
`8f9300cca27890c717fb8c223ccf31a4d7bf780e`

Branch:
`work/0101-telegram-native-ux-navigation-progress-failures`

Workdir:
`/home/rdu01/projects/0101-telegram-native-ux-navigation-progress-failures`

## Order

Implementation phase:

1. A implementation;
2. B implementation;
3. C implementation.

Review phase:

4. A independent review+correction, only if A implementation succeeded;
5. B independent review+correction, only if B implementation succeeded;
6. C independent review+correction, only if C implementation succeeded.

Exactly one spawned subagent may be open at a time.

On the current V1 collaboration surface, a completed agent still counts against
the concurrency cap until closed. After capturing a child's final status/result,
close that child before spawning the next one.

## Workdir discipline

Native subagents inherit the root environment/cwd. Therefore each child must be
explicitly bound to its target checkout.

Before spawning a child, the root verifies the target workdir, branch, issuance,
and clean worktree.

Every child prompt must say:

- all repository reads/writes/tests/Git commands belong to the exact target
  `WORKDIR`;
- every shell call must set that workdir explicitly or begin with
  `cd WORKDIR || exit 1`;
- any patch/edit command must execute from that target checkout;
- never edit the dispatcher/controller checkout;
- never merge/rebase current main merely because it advanced.

The root may synchronously bootstrap a missing target checkout before spawning a
child. Bootstrap shell commands must complete before spawn; no background
processes.

## Clean-context implementation spawn

Spawn each implementation agent with no inherited dispatcher transcript
(`fork_context=false` on V1 or the equivalent clean-context option exposed by
the current tool).

Do not set a custom agent role/type.

Implementation model/effort:
- use the root's configured subagent default: `gpt-6-luna`, `max`;
- an explicit identical override is acceptable when the current spawn schema
  exposes it, but inheritance/default is preferred.

Implementation child prompt:

```text
Work as the implementation+verification agent for buzlet/ah-there-it-is.

Protocol: agent-tasks/common/v9.md
Task: <TASK>
Executor: agent-tasks/executors/u24-direct-shell.md
Issuance: <ISSUANCE>
Branch: <BRANCH>
Workdir: <WORKDIR>

Use only this target checkout. Set <WORKDIR> explicitly for every repository
tool/shell/edit operation. Do not touch the dispatcher checkout.

Follow protocol v9 and the issued batch exactly.
Follow the U24 notification milestone rules.
Do not merge or deploy production.
Open/update the single implementation PR when required by v9.
Wait for required exact-head CI.
Stop at READY FOR REVIEW or a genuine protocol stop condition.
Do not launch another Codex CLI process from shell.
Do not delegate further subagents in this queue.
```

## Native waiting

After spawning one child:

- use the native `wait_agent` tool;
- request a long wait supported by the actual tool, aiming for roughly 2–3
  minutes per check;
- if the tool's runtime clamps to a shorter maximum, accept that maximum and
  wait again without doing duplicate work;
- do not poll OS PIDs;
- do not repeatedly inspect logs while the child is running;
- use `list_agents` only when status clarification is needed.

When the child reaches a final state, record its result, then validate repository
state synchronously.

## Implementation success

An implementation is successful only if:

- child final output contains `READY FOR REVIEW`;
- worktree is clean;
- issuance is an ancestor of final head;
- issued batch file is unchanged in `issuance..HEAD`;
- required PR/CI state is acceptable under the issued batch/protocol.

Record exact implementation head as `I_<batch>`.

Then close the native child before starting the next queue item.

## Failure isolation

A failure in one cluster must not cancel independent later clusters.

For any implementation failure:

1. record cluster status `IMPLEMENTATION_FAILED`;
2. record concise non-secret reason/evidence;
3. send compact dispatcher ntfy milestone;
4. close the failed child if it still exists;
5. continue with the next implementation cluster.

Do not silently restart the same failed implementation in a fresh child.

During review phase, a cluster whose implementation failed is
`REVIEW_SKIPPED_NO_IMPLEMENTATION`; continue with the remaining successful
clusters.

Only stop the entire dispatcher for a genuinely global failure that prevents
safe orchestration of all remaining clusters, for example:
- native multi-agent tools are unavailable/broken for the root;
- root authentication/session is unusable;
- shared filesystem/repository corruption makes all target checkouts unsafe.

A Git/test/product failure confined to one branch is not global.

## Clean-context independent review+correction spawn

For each successful implementation, verify the branch is clean at recorded
`I_<batch>`, then spawn a fresh child with no inherited dispatcher transcript.

Do not pass:
- implementation final handoff;
- PR narrative/self-review;
- implementation conclusions;
- implementer remaining-risk claims.

Review spawn must explicitly request:

- model: `gpt-6-astra`;
- reasoning effort: `medium`.

Do not use a custom `agent_type`. This avoids role-config/model precedence
ambiguity.

If the native spawn schema does not expose a model override, do not silently
substitute Luna. Mark that review `REVIEW_LAUNCH_FAILED_MODEL_OVERRIDE` and
continue to the next eligible review.

Reviewer prompt:

```text
Work as the independent review+correction agent for buzlet/ah-there-it-is.

Protocol: agent-tasks/common/v9.md
Task: <TASK>
Executor: agent-tasks/executors/u24-direct-shell.md
Issuance: <ISSUANCE>
Implementation: <I_SHA>
Branch: <BRANCH>
Workdir: <WORKDIR>

Use only this target checkout. Set <WORKDIR> explicitly for every repository
tool/shell/edit operation. Do not touch the dispatcher checkout.

Reconstruct requirements independently from AGENTS.md, the issued task,
protocol, relevant source/tests and exact implementation code at <I_SHA>.
Do not read or rely on implementation PR narrative/self-review/final handoff
before freezing your own findings.

First complete one full adversarial review pass and send REVIEW PASS.

If clean, perform required verification and finish:
REVIEW COMPLETE — CLEAN

If defects are demonstrated:
- reproduce first where practical;
- add regression first where practical;
- append narrow correction commits to the SAME branch;
- never amend/rebase/squash/force-push;
- send CORRECTIONS DONE after focused correction verification;
- perform final exact-head verification/CI;
- finish:
REVIEW COMPLETE — CORRECTED

Do not merge or deploy production.
Do not launch another Codex CLI process from shell.
Do not delegate further subagents in this queue.
```

## Review success/failure

Success requires terminal marker:

- `REVIEW COMPLETE — CLEAN`, with final head equal to implementation head; or
- `REVIEW COMPLETE — CORRECTED`, with implementation head ancestor of final
  reviewed head.

Also require clean worktree, unchanged issued task, issuance ancestry and
required exact-head CI.

On review failure:

1. record `REVIEW_FAILED`;
2. preserve the branch exactly as left for later human inspection;
3. send compact notification;
4. close the child;
5. continue with the next review.

Do not automatically retry the same review with another model/session.

## Notifications

Root dispatcher uses:

`/home/rdu01/.local/bin/agent-notify`

Minimum dispatcher milestones:

- `DISPATCH START — native 3 clusters`;
- implementation start/result for each cluster;
- `IMPLEMENTATION PHASE COMPLETE` with success/failure counts;
- review start/result for each eligible cluster;
- `DISPATCH COMPLETE` with reviewed/failed/skipped counts.

Children also use normal implementation/reviewer milestones from the executor.

Notification failure is advisory and never changes queue state.

## Final report

Do not merge or deploy.

List each cluster with:

- issuance;
- implementation status and exact implementation head if any;
- review status;
- final reviewed head if any;
- CLEAN/CORRECTED where applicable;
- PR number;
- exact-head CI state;
- concise failure reason when applicable;
- remaining direct follow-up.

Also compare final successful branches for overlapping changed files and identify
likely integration hotspots.

The dispatcher itself must finish even when one or more isolated clusters fail,
unless a global orchestration failure makes further safe work impossible.
