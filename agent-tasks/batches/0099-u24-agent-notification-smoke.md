# Batch: 0099-u24-agent-notification-smoke

Full local required: `false`

## Objective

Verify the U24 agent notification protocol end-to-end with a deliberately small,
non-production task.

This is a notification smoke test, not a product implementation batch.

The run must produce at least five real ntfy milestone messages:

1. START;
2. DONE 1/3;
3. DONE 2/3;
4. DONE 3/3;
5. READY FOR REVIEW.

Use the selected U24 executor notification wrapper exactly as documented.

## Task 1 — message format

Use `AGENT_NOTIFY_DRY_RUN=1` to verify the wrapper output shape.

Confirm:

- first line is Europe/Kyiv `HH:MM`;
- middle line is the milestone text;
- last line has compact limits in the form:
  `100-3:51   90-5:2:20` (values naturally vary);
- the last line contains remaining percentages and relative time-to-reset only;
- no absolute reset timestamp is present.

After verification send the real milestone:

`DONE 0099 1/3 — format verified`

## Task 2 — non-blocking return

Measure one normal wrapper invocation locally.

The invocation must return control immediately rather than waiting for the usage
endpoint or ntfy network request. A detached worker may continue in the
background.

Use this measured invocation itself as the real milestone:

`DONE 0099 2/3 — nonblocking verified`

Report the observed caller-side elapsed time in the final handoff, but keep the
ntfy milestone text minimal.

Notification delivery failure must not become a task failure.

## Task 3 — copy/document consistency

Verify:

- editable/test copy exists at `/home/gpt/.local/bin/agent-notify`;
- runtime copy exists at `/home/rdu01/.local/bin/agent-notify`;
- tracked source exists at `tools/agent/u24_agent_notify.sh`;
- behavior/documentation in `agent-tasks/executors/u24-direct-shell.md` matches
  the tested wrapper;
- no ntfy topic URL or auth token is present in the tracked wrapper.

Do not print secrets while checking.

After verification send:

`DONE 0099 3/3 — copies and docs verified`

## Final milestone

Send:

`READY FOR REVIEW 0099 — notification smoke complete`

before the final textual handoff.

## Scope / safety

- no production inventory mutation;
- no Telegram bot interaction;
- no service restart;
- no provider/model live inference required;
- no repository source edit required;
- do not modify the notification scripts during this smoke run;
- do not create a PR unless a real defect is found that requires a repository
  correction.

## Verification

Read-only checks only. If no defect is found, the work branch may remain exactly
at the issuance SHA.

## Handoff

Stop after the final milestone.

Report:

- exact head SHA;
- whether all five milestone notifications were invoked;
- dry-run format observed;
- caller-side wrapper return latency;
- copy/document consistency result;
- any notification/helper defect found.
