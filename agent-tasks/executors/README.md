# Executor profiles

Executor profiles contain only environment-specific execution rules.

A v9 batch links exactly one profile, for example:

`Executor: agent-tasks/executors/chatgpt-sandbox.md`

The batch must not duplicate profile details such as user, workdir, bootstrap,
network policy or publication mechanics.

Profiles currently available:

- `chatgpt-sandbox.md`
- `u24-direct-shell.md`
- `u24-remote-commander.md`
- `windows-git-bash.md`

Task lifecycle, review and merge policy are defined by
`agent-tasks/common/v9.md`, not by executor profiles.
