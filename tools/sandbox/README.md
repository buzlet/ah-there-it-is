# Sandbox CI bundle

Every `application-ci` run publishes a compact artifact named:

`sandbox-bundle-<github-sha>`

Retention: 5 days.

The bundle is designed for ChatGPT sandbox execution, not as a general Python
distribution.

It contains current application source/tests/eval/prompts, active task/process
material, GNU Makefile/project metadata, agent process tools, and a synthetic local Git baseline tagged `sandbox-base`.

It deliberately contains no Python dependency wheels at all and excludes Python 3.12 artifacts, `just`, the Python `build` package, upstream repository history and archived task material.

Start with:

```bash
make sandbox-bootstrap
```

See `agent-tasks/common/sandbox-execution.md`.
