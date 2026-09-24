# Patch 0041–0050 — storage/recovery hardening

User: `rdu01`
Workdir: `/home/rdu01/projects/storage-recovery-hardening-0041-0050`

Control branch: `queue/post-0040-storage-recovery-hardening`
Immutable SHA: `<CONTROL_SHA>`
Start main: `6e59e0285cf308d8329841ebf40d7162f49bcbec`
Implementation branch: `feat/storage-recovery-hardening-0041-0050`
Manifest: `agent-tasks/batches/post-0040-storage-recovery-hardening/manifest.md`

Ten tasks: 0041 through 0050, in order.

No sudo/su. No other checkout. No shell venv activation/export.
Use `.venv/bin/python` directly and plain `just`.

`full_local_required: true`, but full-local regression runs once only after all ten task checkpoints.
