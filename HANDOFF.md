# Session handoff

## Current authoritative state

Repository: `buzlet/ah-there-it-is`.

Default branch: `main`.

Always verify current `origin/main`, active PRs and CI before starting work. This document is intentionally a current-state handoff, not a chronological stage log.

Historical handoff/status material is archived under `agent-tasks/archive/`.

## Product state

Stages through Stage 26 are complete.

The system currently provides:

- nested inventory Locations/Categories and bounded catalog reads;
- deterministic browser administration/search;
- explicit location truth: known / unknown / in-use / not-applicable;
- sold/discarded terminal lifecycle and explicit reactivation;
- historical Event path snapshots and Activity timeline;
- deterministic RU/UK/EN retrieval baseline;
- provider-neutral deterministic scenario pipeline;
- safe write resolution, atomic agent turns and committed mutation receipts;
- crash-safe request-key idempotency;
- bounded persisted conversation context;
- trace-config privacy;
- doctor/FTS repair;
- backup/restore/restore rehearsal;
- portable-v2 export/import with frozen v1 import support;
- stable per-user data home and installed runtime CLI.

Assignment 0029 prepared host-selected development under protocol v6. Protocol v7 is the current active process generation.

## Current process

Active protocol:

`agent-tasks/common/v7.md`

Do not read historical protocols by default.

v7 currently supports:

1. U24 Bash through Remote Commander.
2. U24 Bash through a transparently connected direct shell.
3. Windows Git Bash through Remote Commander, prepared but still pending native Windows pilot.

For the direct U24 shell channel there is no SSH command and no nested Codex process. The environment is already connected to U24. Development must be performed as local OS user `gpt` with:

- `HOME=/home/gpt`;
- repository `/home/gpt/projects/ah-there-it-is`;
- repository `.venv` Python.

If the connected environment starts as another user, switch locally to `gpt` before repository operations. Failure to become `gpt` is a blocker.

## Canonical checks

```text
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
just provider-contract
```

Coverage is collected only in application CI and is currently report-only.

## Important invariants

- LLM never writes the database directly.
- Service/domain layer owns writes and history.
- Search ranking does not grant write authority.
- Agent turns are atomic.
- Retry-safe chat idempotency prevents duplicate mutation after uncertain response.
- Current Location truth is explicit and independent from Item condition/state.
- Historical paths come from Event-time snapshots where available.
- Startup does not auto-migrate/repair.
- Backup/restore and portable import are separate products.
- No ordinary hard delete exists.

## Documentation reading policy

Normal implementation reading:

- `AGENTS.md`;
- exact issued assignment/manifest;
- `agent-tasks/common/v7.md`;
- relevant source/tests.

The archive is not ordinary context:

`agent-tasks/archive/`

Open archived material only to investigate a historical decision, regression or exact old contract.

## Next decision gate

Quantity / physical-instance semantics remain unresolved.

Do not implement partial quantity move/sale/disposal or Item split/merge until this gate is explicitly decided.

Other deferred gates:

- correction/undo UX;
- archive/hard-delete semantics if ever needed;
- raw agent trace retention;
- automated backup retention/scheduling;
- remote authentication / multi-user ownership;
- voice/image/QR/chat integrations;
- provider/model promotion policy.

See `agent-tasks/designs/future-decision-gates.md`.

## Development environment

U24 established development account:

- user: `gpt`;
- home: `/home/gpt`;
- repo: `/home/gpt/projects/ah-there-it-is`;
- venv: repository `.venv`.

Every independent command execution must re-establish the repo and venv prelude.

Windows Git Bash support has been prepared but should not be called validated until a native pilot completes.
