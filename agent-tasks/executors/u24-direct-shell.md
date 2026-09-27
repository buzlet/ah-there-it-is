# Executor: U24 direct shell

Status: supported and preferred for target-server/deployment work.

## Identity

```text
host_profile: u24-bash
execution_channel: direct-shell
execution_user: rdu01
HOME: /home/rdu01
```

Do not use `sudo`, `su` or another OS user.

## Workdir

For batch file:

`agent-tasks/batches/<batch-id>.md`

use the unique checkout:

`/home/rdu01/projects/<batch-id>`

All Git, edits, Python, Make and tests stay inside that checkout.

Before mutation verify:

```bash
test "$(id -un)" = "rdu01"
test "$HOME" = "/home/rdu01"
test "$PWD" = "/home/rdu01/projects/<batch-id>"
git rev-parse --show-toplevel
git branch --show-current
```

The current branch must be `work/<batch-id>`, pre-created by the orchestrator,
and the issuance SHA must be its ancestor.

Do not require current `origin/main` to equal the issuance SHA.

## Checkout/bootstrap

If the exact issued checkout does not exist, create a fresh canonical checkout in
the required workdir and check out `work/<batch-id>`.

Use the repository-local `.venv`.

Direct Python commands use:

`.venv/bin/python ...`

GNU Make recipes are canonical.

Do not export a modified PATH and do not activate the venv globally.

## Network/publication

The direct executor may use the server's normal repository connectivity for the
issued checkout when required, but GitHub orchestration/PR actions should use the
GitHub connector when available.

Do not make unrelated external/provider/Telegram calls unless the batch explicitly
requires them.

## Target-server role

This executor runs on the machine intended for deployment. Host-specific MVP work
belongs here rather than in sandbox when the batch selects this executor, including
service-manager behavior, filesystem/env/secrets placement, restart rehearsal and
other real-host checks explicitly listed by the task.

Do not infer new product semantics from deployment observations.

## Verification authority

Local Direct checks validate the real host/environment.

Python 3.12 application CI on the exact remote PR head remains the repository-wide
merge gate unless the batch explicitly declares additional host acceptance checks.


## User notifications

Canonical host sender:

`/home/gpt/.local/bin/notify`

Editable/test copy of the agent wrapper:

`/home/gpt/.local/bin/agent-notify`

Runtime copy for agents running as `rdu01`:

`/home/rdu01/.local/bin/agent-notify`

Tracked source: `tools/agent/u24_agent_notify.sh`.

The wrapper is deliberately non-blocking. A normal invocation detaches a worker
and returns control immediately; notification/usage network failure must never
delay or fail the agent task. `AGENT_NOTIFY_DRY_RUN=1` runs the worker in the
foreground and prints the exact message body without sending, for format tests.

Usage retrieval is implemented directly inside the wrapper. It does not call a
separate usage helper.

Every notification body is exactly three logical parts:

1. first line: send time in Europe/Kyiv, `HH:MM`;
2. middle: one compact milestone message;
3. last line: 5-hour and weekly remaining limits.

Compact limit format:

```text
100-3:51   90-5:2:20
```

Meaning:

- `100-3:51` = 100% of the 5-hour limit remains; 3h51m until reset;
- `90-5:2:20` = 90% of the weekly limit remains; 5d2h20m until reset.

Use remaining percentages only. Never include absolute reset timestamps.

Always invoke notifications as best-effort:

```bash
/home/rdu01/.local/bin/agent-notify "MESSAGE" "u24" default || true
```

Never include secrets, tokens, auth material, private payloads, or long logs.

### Implementation agent milestones

Send:

1. **START** — once, after identity/workdir/branch/issuance checks succeed and
   immediately before substantive work begins.
2. **TASK DONE** — once after each meaningful top-level implementation work unit
   from the issued batch is actually complete, including its focused verification
   when that verification belongs to the work unit.
   - Use the batch's numbered Scope/Required sections as the default granularity.
   - Do not notify for every sub-bullet, file edit, test case, command, or trivial
     documentation step.
   - If several tiny adjacent sections are inseparable in implementation, one
     combined milestone is acceptable and should name all completed sections.
3. **READY FOR REVIEW** — once, when implementation has reached its final stop
   condition. Include the batch id, final head SHA, and PR/CI state when known.

### Reviewer milestones

Send:

1. **START REVIEW** — after the exact implementation head and review scope are
   verified, before substantive inspection.
2. **REVIEW PASS** — mandatory midpoint notification after one full independent
   pass over the relevant diff/code/tests. Report `CLEAN` or a concise
   finding count/category and that correction is starting.
3. **CORRECTIONS DONE** — only when corrections were required; send after all
   reviewer corrections plus focused verification and before final exact-head
   verification/CI.
4. **REVIEW COMPLETE** — final notification with `CLEAN` or `CORRECTED`,
   final head SHA, and CI state when known.

The midpoint criterion is semantic, not time-based. Do not send periodic
heartbeat spam merely because work is taking time.

### Failure / interruption notification

If the agent must stop before its normal final milestone because of a real stop
condition, send one concise `STOPPED` notification describing the non-secret
reason category before handing control back, when possible.

Notification transport failure is never itself a task failure.
