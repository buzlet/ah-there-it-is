# Launcher for Assignment 0029

This enabling assignment intentionally runs on U24 using the existing v5/v4 protocol.

Use the immutable control SHA supplied with this launcher.

```text
Работай как autonomous implementation+verification agent проекта `buzlet/ah-there-it-is`.

Для ЭТОГО enablement assignment используй существующий execution path:
- execution profile: `u24-bash`
- Remote Commander device: `u24-gpt`
- repo path: `/home/gpt/projects/ah-there-it-is`

Batch control:
- branch: `queue/windows-git-bash-enablement-v2`
- immutable control SHA: `<CONTROL_SHA>`
- manifest: `agent-tasks/batches/windows-git-bash-enablement/manifest.md`

Start prerequisite:
- `origin/main` must equal `f5a05fa4b723ed1bca37b8137f445594f58fdebd`.

Прочитай из control SHA:
`agent-tasks/common/v5-batch.md`
и manifest.

Создай just-in-time seed Assignment 0029 из точной pre-issued specification и выполни полный implementation/self-review/focused+canonical verification/PR/CI/merge lifecycle.

Для всех независимых Remote Commander command batches не полагайся на сохранённый shell state. Каждый batch явно начинает с:
`cd /home/gpt/projects/ah-there-it-is && export PATH="$PWD/.venv/bin:$PATH"`

Canonical Just recipes вызывай в их default-форме без самодельных positional аргументов.

Не используй бесконечный интерактивный CI watcher; ожидание CI должно быть ограниченным и наблюдаемым.

Цель Assignment 0029:
- подготовить host-aware protocol v6;
- сохранить U24/Bash path;
- добавить Windows 11 / Git Bash path;
- сделать canonical verification harness переносимым;
- не добавлять PowerShell/cmd implementation path;
- не добавлять Windows CI matrix;
- не менять historical v4/v5;
- не заявлять native Windows validation, поскольку 0029 выполняется на U24.

После merge 0029 остановись и верни compact report.

Первый настоящий `windows-git-bash` lifecycle будет отдельным pilot assignment.
```
