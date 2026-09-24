# Patch 0040 — streaming evaluation export

User: `rdu01`

Workdir:

`/home/rdu01/projects/streaming-evaluation-export-0040`

Control branch:

`queue/post-0039-streaming-evaluation-export`

Immutable control SHA:

`<CONTROL_SHA>`

Start main:

`821910c1db1a65f06f3184321baa8683a1a87402`

Implementation branch:

`feat/streaming-evaluation-export-0040`

Manifest:

`agent-tasks/batches/post-0039-streaming-evaluation-export/manifest.md`

No sudo/su and no other checkout.

Do not export/activate the venv in the shell.

Use `.venv/bin/python` for direct Python and plain `just` for recipes.

Implement only 0040, run its focused checks, one final PR/CI, merge commit, then compact report.
