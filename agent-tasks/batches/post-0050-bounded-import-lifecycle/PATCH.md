# Patch 0051–0060 — bounded portable import and lifecycle alignment

User: `rdu01`
Workdir: `/home/rdu01/projects/bounded-import-lifecycle-0051-0060`

Control branch: `queue/post-0050-bounded-import-lifecycle`
Immutable SHA: `<CONTROL_SHA>`
Start main: `c6609139e16384e3de48f9b403a426dcf2fa9e9c`
Implementation branch: `feat/bounded-import-lifecycle-0051-0060`
Manifest: `agent-tasks/batches/post-0050-bounded-import-lifecycle/manifest.md`

Ten ordered tasks: 0051 through 0060.

0051–0058 finish bounded storage/portable-import work.
0059–0060 align lifecycle tooling with the actual v8 integrated-batch model.

No sudo/su. No other checkout. No shell venv activation/PATH export.
Use `.venv/bin/python` directly and plain `just`.

`full_local_required: true`, but full-local regression runs once only after all ten checkpoints.
