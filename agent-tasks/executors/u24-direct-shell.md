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

This executor has a host-local best-effort notification helper:

`/home/rdu01/.local/bin/notify`

Notifications are operational UX only. They must never change task outcome,
transaction semantics, Git state, verification, or stop conditions.

Always invoke notifications as best-effort:

```bash
/home/rdu01/.local/bin/notify "MESSAGE" "TITLE" default || true
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

Suggested compact messages:

```text
START 0098 implementation — configuration boundary audit
DONE 0098 2/6 — candidate inventory + classification
READY FOR REVIEW 0098 — head abc1234 — CI green
```

### Reviewer milestones

Send:

1. **START REVIEW** — after the exact implementation head and review scope are
   verified, before substantive inspection.
2. **REVIEW PASS** — mandatory midpoint notification after the reviewer has
   completed one full independent pass over the relevant diff/code/tests and has
   classified the result:
   - `CLEAN`, or
   - number/short categories of findings and that correction is starting.
3. **CORRECTIONS DONE** — only when corrections were required; send after all
   reviewer corrections plus their focused verification are complete and before
   final exact-head verification/CI.
4. **REVIEW COMPLETE** — final notification with `CLEAN` or `CORRECTED`,
   final head SHA, and CI state when known.

Suggested compact messages:

```text
START REVIEW 0098 — head abc1234
REVIEW PASS 0098 — 2 findings — correcting
CORRECTIONS DONE 0098 — head def5678 — final verification
REVIEW COMPLETE 0098 — CORRECTED — head def5678 — CI green
```

The midpoint criterion is semantic, not time-based: completing the first full
review pass is the reliable point at which the reviewer knows whether the work is
clean or what must be corrected. Do not send periodic heartbeat spam merely
because review is taking time.

### Failure / interruption notification

If the agent must stop before its normal final milestone because of a real stop
condition, send one concise `STOPPED` notification describing the non-secret
reason category before handing control back, when possible.

Notification transport failure is never itself a task failure.
