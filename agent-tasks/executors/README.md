# Executor profiles

Executor profiles contain only environment-specific execution rules.

Task and executor are selected independently. A v9 handoff supplies, for example:

```text
Task: agent-tasks/batches/0091-deployment-readiness.md
Executor: agent-tasks/executors/u24-direct-shell.md
Issuance: <sha>
```

Both files are read from the issuance SHA.

The task must not duplicate profile details such as user, workdir, bootstrap,
network policy or publication mechanics. The executor must not contain task
scope/lifecycle/review policy.

Profiles currently available:

- `chatgpt-sandbox.md`
- `u24-direct-shell.md`
- `u24-remote-commander.md`
- `windows-git-bash.md`

Task lifecycle, review and merge policy are defined by
`agent-tasks/common/v9.md`.
