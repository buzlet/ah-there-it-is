# Patch 0035–0039 v4

User: `rdu01`

Workdir:

`/home/rdu01/projects/operational-read-scalability-0035-0039-v4`

Control:
- branch: `queue/post-0034-operational-read-scalability-v4`
- immutable SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0034-operational-read-scalability-v4/manifest.md`
- start main: `471fc313ec532371e860f1a72ba38544b5a9376e`
- implementation branch: `feat/operational-read-scalability-v4`

Run the full user/HOME/Git-toplevel/venv preflight once at batch startup.

After that, later shell calls only re-enter the exact workdir and restore repo-local venv PATH. Do not repeat identity/toplevel checks before every mutation.

No sudo/su, no other checkout.

Execute 0035–0039 with focused checkpoints, no local full repository suite, one final PR and one authoritative CI.
