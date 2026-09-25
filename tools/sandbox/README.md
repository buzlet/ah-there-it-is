# Sandbox CI bundle

Every `application-ci` run publishes a compact artifact named:

`sandbox-bundle-<github-sha>`

Retention: 5 days.

The bundle is designed for ChatGPT sandbox execution, not as a general Python
distribution.

It contains current application source/tests/eval/prompts, active task/process
material, GNU Makefile/project metadata, agent process tools, and exact source metadata. `make sandbox-bootstrap` creates the synthetic local Git baseline and `sandbox-base` tag after extraction.

It deliberately contains no Python dependency wheels at all and excludes Python 3.12 artifacts, `just`, the Python `build` package, upstream repository history, synthetic Git objects, and archived task material.

Start with:

```bash
make sandbox-bootstrap
```

Bootstrap validates only dependencies declared by this project; unrelated conflicts elsewhere in the shared sandbox image do not block it.

See `agent-tasks/common/sandbox-execution.md`.
