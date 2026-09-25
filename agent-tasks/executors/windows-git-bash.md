# Executor: Windows Git Bash

Status: pending native validation.

Do not select this executor for implementation unless the orchestrator explicitly
states that native validation has been completed for the issued batch.

## Intended environment

Windows Git Bash reached through the authorized Remote Commander connection.

The exact Windows user, repository path, venv/bootstrap rules and command
compatibility must be validated before this profile becomes generally supported.

## Until validated

If selected accidentally, stop before mutation and report:

`executor windows-git-bash is not yet validated for normal implementation`

Do not substitute PowerShell, WSL, Windows Sandbox or another environment without
a new explicit executor selection.
