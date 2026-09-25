# Executor: U24 Remote Commander

Status: supported when explicitly selected.

## Identity

```text
host_profile: u24-bash
execution_channel: remote-commander
target_user: gpt
repo_path: /home/gpt/projects/ah-there-it-is
```

Use only the authorized U24 Remote Commander connection.

Do not switch users or use sudo/su unless a future executor revision explicitly
authorizes it.

## Checkout exclusivity

This profile uses the existing `gpt` repository path.

The orchestrator must ensure that no concurrent implementation is using the same
checkout before selecting this executor.

The checkout must be on the issued implementation branch and the issuance SHA
must be an ancestor of HEAD.

Do not require current `origin/main` to equal the issuance SHA.

## Commands

Run repository commands only in:

`/home/gpt/projects/ah-there-it-is`

Use the repository-local Python/Make conventions already present there.

Do not create nested agents or SSH sessions from inside Remote Commander.

## Network/publication

Use Remote Commander for filesystem/terminal execution.

Use the GitHub connector for PR/orchestration actions when available.

External provider/Telegram/network activity is allowed only when the issued batch
explicitly requires it.

## Verification authority

Remote Commander results are host execution evidence.

Python 3.12 application CI on the exact remote PR head remains authoritative for
repository-wide regression.
