# Candidate parallel task — executor-boundary hardening

Status: draft only. Do not execute on the working tree used by batch 0061-0070.

## Why this is independent

This task touches process tooling only:

- `tools/agent/lifecycle_checkpoints.py`;
- `tools/agent/process_state.py` if needed;
- process-tool tests/documentation.

It should not touch inventory runtime, schema, agent business behavior, portable format or web code.

## Current gap

Integrated-v8 manifests currently parse execution user and workdir, but execution-channel/device constraints are mostly launcher prose. The implementation process repeatedly relies on shell assertions to detect wrong user/path.

The recent change from direct-shell/rdu01 to Remote Commander/gpt demonstrates why these facts should be machine-checkable.

## Proposed scope

Extend integrated manifest parsing/preflight to optionally understand:

```text
Execution channel:
remote-commander | direct-shell

Remote Commander device:
u24-gpt

Execution user:
gpt

Required work directory:
/home/gpt/projects/ah-there-it-is
```

Preflight should verify what it can locally:

- actual repository path;
- current OS user;
- HOME when declared;
- current branch/start-main/control;
- clean worktree;
- manifest execution metadata consistency.

A local process tool cannot prove which ChatGPT connector/device invoked the shell. Device/channel fields should therefore be validated as manifest metadata and exposed in machine-readable preflight output, not falsely claimed as independently attested.

## Non-goals

- no SSH/session setup;
- no sudo/user switching;
- no nested agent launcher;
- no inventory code;
- no modification of active 0061-0070 control;
- no weakening of existing v8 compatibility.

## Focused tests

Add cases for:

- direct-shell manifest;
- remote-commander manifest;
- wrong local user;
- wrong repo/workdir;
- missing/malformed optional execution metadata;
- old integrated manifests remaining parseable;
- legacy manifests unchanged.

## Execution prerequisite

Run only when a **separate checkout or device** is available.

Do not switch the branch of `/home/gpt/projects/ah-there-it-is` while 0061-0070 owns that checkout.
