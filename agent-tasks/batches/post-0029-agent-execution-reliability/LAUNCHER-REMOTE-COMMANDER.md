# Launcher — U24 Remote Commander

```text
Работай как autonomous batch implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol:
- `agent-tasks/common/v7.md`

Execution:
- host_profile: `u24-bash`
- execution_channel: `remote-commander`
- device: `u24-gpt`
- repo_path: `/home/gpt/projects/ah-there-it-is`

Batch control:
- branch: `queue/post-0029-agent-execution-reliability`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/post-0029-agent-execution-reliability/manifest.md`

Выполни весь batch:
`0030 → 0031 → 0032 → 0033 → 0034`
по v7 последовательно, с отдельным seed/PR/CI/merge для каждой задачи.

После 0034 остановись и верни compact batch report.
```
