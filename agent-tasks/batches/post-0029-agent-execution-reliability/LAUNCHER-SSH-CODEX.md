# Launcher — U24 SSH + Codex CLI

Replace the placeholders with the user's already configured SSH target, U24 repository path and Codex command.

```text
Работай как controller автономного implementation+verification batch проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v7.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `ssh-codex`
- ssh_target: `<SSH_TARGET>`
- repo_path: `<U24_REPO_PATH>`
- codex_bin: `<CODEX_BIN>`

Batch control:
- branch: `queue/post-0029-agent-execution-reliability`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0029-agent-execution-reliability/manifest.md`

Используй SSH только как транспорт и канал надзора. Реализацию, изменения репозитория, тесты, PR/CI correction loop и merge выполняет Codex CLI на U24 в соответствии с v7.

Для Codex используй non-interactive structured transport `codex exec --json --full-auto -`, передавая точный issued prompt через stdin.

Выполни batch последовательно:
`0030 → 0031 → 0032 → 0033 → 0034`.

Не запускай второй Codex process для той же задачи, пока первый не доказанно завершён. При SSH disconnect сначала восстанови соединение и проверь durable process/repository state.

После каждого успешного merge переходи к следующей pre-issued задаче без изменения host/channel. При stop condition остановись с compact blocker report. После 0034 верни compact batch report.
```
