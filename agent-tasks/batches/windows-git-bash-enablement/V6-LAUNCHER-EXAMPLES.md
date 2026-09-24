# v6 launcher contract examples

These are the required user/orchestrator-facing execution selectors that Assignment 0029 must preserve in the resulting v6 protocol.

## U24

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol: `agent-tasks/common/v6.md`

Execution:
- execution_profile: `u24-bash`
- device: `u24-gpt`
- repo_path: `/home/gpt/projects/ah-there-it-is`

<assignment/batch control fields here>

Выполни lifecycle выбранного assignment/batch по v6.
```

## Windows 11 + Git Bash

```text
Работай как implementation+verification agent проекта `buzlet/ah-there-it-is`.

Protocol: `agent-tasks/common/v6.md`

Execution:
- execution_profile: `windows-git-bash`
- device: `<windows Remote Commander device>`
- repo_path: `/c/<path>/ah-there-it-is`
- git_bash_exe: `C:\Program Files\Git\bin\bash.exe`

Все repository/Git/test/verification команды выполняй только через Git Bash на указанном Windows device. Не переключайся на PowerShell, cmd, WSL или U24.

<assignment/batch control fields here>

Выполни lifecycle выбранного assignment/batch по v6.
```

The user/orchestrator supplies the exact Windows Remote Commander device and repository path. The agent never guesses them.
