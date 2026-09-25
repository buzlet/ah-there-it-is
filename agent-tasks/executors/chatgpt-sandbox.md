# Executor: ChatGPT sandbox

Status: supported.

## Identity

```text
host_profile: chatgpt-sandbox
execution_channel: sandbox
execution_user: sandbox
```

## Workdir

For the separately supplied task:

`agent-tasks/batches/<batch-id>.md`

use:

`/mnt/data/<batch-id>`

All edits, local Git commits, tests and generated handoff material stay under that
directory.

## Source

Use the exact CI artifact:

`sandbox-bundle-<issuance-sha>`

Discover/download it through the GitHub connector. No artifact ID needs to be
stored in the batch.

After extraction verify `.sandbox/MANIFEST.txt`:

- `repository=buzlet/ah-there-it-is`;
- `source_commit=<issuance-sha>`.

If the exact artifact expired, rerun CI for that issuance SHA or ask the
orchestrator to reissue. Do not silently use another SHA.

## Bootstrap

Run:

`make sandbox-bootstrap`

It creates the local venv/synthetic Git baseline and installs this project using
the preinstalled offline dependency environment.

The local synthetic commit/tag is execution evidence only and is never an
upstream provenance SHA.

## Network and dependencies

Shell network is forbidden.

Do not use:

- shell `git fetch/push`;
- curl/wget;
- online pip/uv;
- ad-hoc dependency downloads;
- live provider/Telegram calls unless a future batch explicitly changes policy.

GitHub reads/writes use the GitHub connector.

If a declared dependency is missing/incompatible, stop and report the sandbox
image mismatch. Do not modify project dependencies merely to repair the sandbox.

## Commands

GNU Make is canonical.

- direct Python: `.venv/bin/python ...`
- repeated checks: `make ...`
- do not install/use `just`.

## Publication

The orchestrator pre-creates `work/<batch-id>` from the issuance SHA.

Publish append-only implementation/reviewer commits to that branch through the
GitHub connector.

Do not rebase or force-push because `main` advanced.

If connector publication is unavailable, export a patch/handoff relative to the
synthetic baseline and report remote publication/CI as pending.

## Verification authority

Sandbox Python is implementation evidence.

Python 3.12 application CI on the exact remote PR head is authoritative.
