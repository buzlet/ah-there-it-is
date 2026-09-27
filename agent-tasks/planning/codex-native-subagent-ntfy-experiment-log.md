# Codex native subagent + ntfy orchestration experiment log

Date: 2026-09-27
Host: U24
Execution user: rdu01
Codex CLI observed: 0.156.1

## Goal

Find a reliable way for one long-lived Codex dispatcher to execute a queue of
implementation and review/correction agents without manually starting each
agent, while preserving:

- exact model/reasoning selection;
- one active child at a time;
- independent review context;
- per-cluster failure isolation;
- durable milestone notifications;
- existing v9 branch/issuance discipline.

## Experiment 1 — nested Codex CLI launched from a Codex shell tool

The first dispatcher attempted to start another CLI process from its shell tool:

```bash
nohup codex exec ... > child.log 2>&1 &
```

Observed result:

- dispatcher itself remained healthy;
- recorded nested PID exited almost immediately;
- durable nested log was zero bytes;
- no `READY FOR REVIEW` marker existed;
- target checkout remained unchanged at issuance;
- dispatcher correctly stopped rather than silently retrying.

Important control experiment:

The equivalent `nohup codex exec ...` launcher works when invoked from an
ordinary host shell outside a Codex tool call.

Conclusion:

> Do not use background OS descendants created inside a Codex shell tool as
> durable nested agents.

The evidence is consistent with the shell-tool execution lifecycle cleaning up
background descendants after the tool call completes. Whether this is implemented
by process groups, cgroups or another runner mechanism is not required knowledge
for the operational rule.

## Experiment 2 — built-in Codex multi-agent support

`codex features list` on CLI 0.156.1 reported:

- `multi_agent`: stable, enabled;
- `multi_agent_v2`: stable, disabled.

A native collaboration test was run without invoking a nested CLI:

1. root: `gpt-6-luna`;
2. root spawned child: `gpt-6-astra`, medium reasoning;
3. child spawned grandchild: `gpt-6-luna`, low reasoning;
4. grandchild returned `GRANDCHILD_OK`;
5. child waited and returned `CHILD_OK GRANDCHILD_OK`;
6. root waited and returned `ROOT_OK CHILD_OK GRANDCHILD_OK`.

Result: success.

This proves for the tested CLI/runtime:

- a Codex agent can spawn a native subagent;
- a spawned child can itself spawn a subagent when depth/config allows it;
- explicit child model/reasoning selection works on the native collaboration
  surface;
- shell-level nested Codex processes are unnecessary.

## Model/reasoning configuration

Useful root configuration keys observed/tested:

```text
agents.max_concurrent_threads_per_session
agents.default_subagent_model
agents.default_subagent_reasoning_effort
```

Dispatcher policy used:

```text
root dispatcher:
  gpt-6-luna / max

implementation children:
  default gpt-6-luna / max

review+correction children:
  explicit gpt-6-astra / medium

max concurrent child agents:
  1
```

Recommended root CLI configuration:

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

Do not introduce a custom `agent_type` merely to choose implementation/reviewer
models. Explicit reviewer model/reasoning overrides are clearer and avoid
role/config precedence ambiguity.

## Native dispatcher operating rule

The reliable pattern is:

```text
root dispatcher
  -> spawn one native implementation child
  -> native wait
  -> validate branch/head/CI
  -> close child
  -> next implementation
  ...
  -> spawn one fresh independent reviewer child
  -> native wait
  -> reviewer corrects same branch when required
  -> validate branch/head/CI
  -> close child
  -> next review
```

Do not poll OS PIDs for native subagents.

Use the native wait/list/close collaboration tools. A completed V1 child may
still count toward concurrency until closed, so capture its result and close it
before spawning the next child.

## Independent review isolation

Review children are started with a clean context.

They receive only:

- task;
- executor;
- issuance;
- exact implementation SHA;
- branch/workdir;
- v9 review instructions.

Before freezing their own findings they do not consume:

- implementation handoff;
- PR self-review narrative;
- implementation conclusions;
- implementer remaining-risk claims.

The same reviewer agent is also the correction agent. It appends fixes/tests to
the same work branch and never amends/rebases/force-pushes prior implementation
history.

## Failure-isolation policy

The first dispatcher stopped the entire queue when one child launch failed. That
is too strict for independent clusters.

Revised rule:

- a cluster-local implementation/review failure is recorded and notified;
- the failed child is closed;
- no automatic retry of that same cluster is performed;
- independent later clusters continue;
- review is skipped only for a cluster whose implementation failed;
- the entire dispatcher stops only for a genuinely global orchestration failure.

Examples of global failures:

- native collaboration tools unavailable;
- root auth/session unusable;
- shared repository/filesystem corruption makes all remaining checkouts unsafe.

## Full native-dispatcher run

The native dispatcher successfully completed three sequential implementation
agents followed by three sequential independent review+correction agents.

### Configuration audit

- issuance: `d896ad3a9894cb3a706c9ce3087d6922f11ee93b`
- implementation: `03a877a601599cd8fa832c366438766492216735`
- reviewed/corrected: `53339676728a21d9f499414f7cd335171e96d213`
- PR: #102
- exact-head CI: green

### Russian semantics

- issuance: `efc0bc3fb7d44ebd42dd925da48cb393c23ba7c0`
- implementation: `cac1925ea34114cc3d09b8493ec17cfa928849e1`
- reviewed/corrected: `7589295df211e3561a75d633bf484cf5660b94c1`
- PR: #103
- exact-head CI: green

### Telegram UX/runtime

- issuance: `8f9300cca27890c717fb8c223ccf31a4d7bf780e`
- implementation: `d89a7791c153ada39792ee10ac45cb58c780d455`
- reviewed/corrected: `da4f17d2889bb408170734b34e3ef0126b2e9651`
- PR: #104
- exact-head CI: green

All three final branches were clean and retained issuance ancestry. No final
branches had overlapping changed file paths. Russian semantics and Telegram UX
still have a semantic integration boundary and therefore require combined
post-merge verification.

## ntfy experiment

Canonical sender:

`/home/gpt/.local/bin/notify`

Editable wrapper:

`/home/gpt/.local/bin/agent-notify`

Runtime wrapper for agents:

`/home/rdu01/.local/bin/agent-notify`

Tracked source:

`tools/agent/u24_agent_notify.sh`

### Failed design

The wrapper originally did:

```bash
nohup "$0" --worker ... &
```

This has the same lifecycle hazard as nested Codex CLI when called from a Codex
shell tool: the background worker can disappear when the tool call finishes.

### Reliable design

The wrapper now submits a short transient user service:

```text
systemd-run --user --no-block ...
```

Properties:

- caller returns immediately;
- network work runs outside the shell-tool lifecycle;
- transient worker has a short runtime bound;
- sender itself has a short timeout;
- notification failure is advisory and never changes task state.

The U24 `rdu01` user systemd manager was verified running. A notification
invoked from inside a Codex shell tool was observed creating the transient
`agent-notify-...` service successfully after the tool call returned.

### Message format

Minimal body:

```text
HH:MM
MILESTONE
100-3:51   90-5:2:20
```

Meaning:

- first line: Europe/Kyiv send time;
- second line: compact milestone;
- last line:
  - 5-hour remaining percentage + hours:minutes until reset;
  - weekly remaining percentage + days:hours:minutes until reset.

The limit query is implemented inside the wrapper so agents do not need a
separate usage command.

## Notification milestones

Implementation child:

- START;
- one DONE per meaningful top-level task unit;
- READY FOR REVIEW;
- STOPPED when applicable.

Reviewer/correction child:

- START REVIEW;
- REVIEW PASS after the first complete independent pass;
- CORRECTIONS DONE if corrections were required;
- REVIEW COMPLETE CLEAN/CORRECTED;
- STOPPED when applicable.

Root dispatcher additionally emits queue/cluster transitions.

## Remaining limitations / future experiments

1. ntfy delivery is best-effort. Successful transient-worker execution proves the
   local send attempt, not that the phone client displayed the notification.
   Add optional local success/failure journaling if delivery diagnostics become
   important.
2. Native multi-agent tool schemas/config may evolve with Codex versions. Re-run
   a minimal Luna -> Astra -> Luna chain after substantial CLI upgrades before
   relying on orchestration for a long queue.
3. Keep root concurrency at 1 for branch-mutating work unless the checkout model
   is deliberately redesigned for safe parallelism.
4. Keep per-cluster workdirs separate and explicit because native children inherit
   root environment/context unless told otherwise.
5. The dispatcher should never merge or deploy; integration remains a separate
   orchestrator step after all final reviewed heads are known.

## Operational default

For future U24 multi-batch orchestration:

> Prefer one Luna/max root dispatcher using native Codex subagents, Luna/max
> implementation children, Astra/medium review+correction children, concurrency
> 1, clean reviewer context, cluster-local failure isolation, and systemd-backed
> best-effort ntfy milestones.

Do not return to shell-spawned nested Codex processes unless a future measured
test proves their lifecycle semantics changed.
