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
