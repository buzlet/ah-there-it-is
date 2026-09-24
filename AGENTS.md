# AGENTS.md

## Purpose

Authoritative current architecture and implementation rules for `buzlet/ah-there-it-is`.

Read this file, the explicitly issued assignment/manifest, and the active protocol. Do **not** bulk-read `agent-tasks/archive/` unless the assignment explicitly requires historical investigation.

## Product

“Ah, There It Is!” is a local-first personal inventory memory.

Target scale remains roughly:

- 100–250 nested Locations;
- about 1000 Items;
- deterministic text/browser workflows;
- provider-neutral LLM assistance.

## Architecture invariants

### Domain and persistence

- SQLite + SQLAlchemy are authoritative persistence.
- Domain/service code owns validation, identity, invariants, transactions and mutation history.
- The LLM never accesses the database directly.
- Stable IDs are preserved.
- Normal Item mutations create truthful immutable domain history.
- Startup does not auto-migrate or auto-repair the active database.

### Agent safety

- Search ranking does not authorize writes.
- Existing write targets require strong resolver evidence and atomic revalidation before mutation.
- Agent turns are transactionally atomic.
- Mutation-tool errors fail the turn; successful committed changes have typed receipts.
- Failed turns do not become normal conversation history.
- Request-key idempotency owns crash-safe replay semantics.

### Location truth

`Item.location_status` is authoritative:

- `known` iff a current Location exists;
- `unknown`: whereabouts unknown;
- `in_use`: intentionally outside storage;
- `not_applicable`: terminal Item.

`sold` and `discarded` are terminal and require `not_applicable`.

Moves, take/in-use, mark-location-unknown, sold/discarded and reactivation are explicit operations. Generic update is not a back door around these transitions.

### Search

- Deterministic bounded SQL/FTS retrieval.
- Stable ranking semantics.
- Current offline retrieval corpus is RU/UK/EN and gating.
- Fuzzy matching, transliteration, morphology/stemming and embeddings are deferred unless future measured evidence justifies them.

### History

New Events retain historical Location/Category path evidence in payload snapshots. Current tree paths must never be presented as historical truth when no snapshot exists.

### Recovery

- Full SQLite backup/restore is distinct from portable inventory import.
- Portable current format is v2; frozen v1 remains importable.
- Bootstrap remains a separate onboarding contract.
- Doctor is read-only except the explicit derived FTS repair command.

## Development rules

- Make the smallest coherent change required by the assignment.
- No opportunistic dependency/runtime/workflow upgrades.
- No provider-specific application semantics.
- No speculative Windows skips/xfails.
- Tests use structural/deterministic assertions rather than timing gates where practical.
- Keep worktree clean after verification.
- Use merge commits for implementation PRs so immutable seed ancestry remains visible.

## Canonical verification

Run on final implementation HEAD:

```text
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
just provider-contract
```

Focused checks supplement, not replace, this set.

## Current implementation protocol

Use only:

`agent-tasks/common/v7.md`

unless an immutable already-running control SHA explicitly issued an older protocol.

Historical protocol generations are archived and should not be read during ordinary work.

## v7 execution model

v7 separates the **host profile** from the **execution channel**.

### U24 through Remote Commander

```text
host_profile: u24-bash
execution_channel: remote-commander
device: u24-gpt
repo_path: /home/gpt/projects/ah-there-it-is
target_user: gpt
```

Remote Commander performs repository/terminal work on the selected device.

### U24 through a transparently connected Codex environment

```text
host_profile: u24-bash
execution_channel: direct-shell
repo_path: /home/gpt/projects/ah-there-it-is
target_user: gpt
```

The execution environment is already connected to U24. There is **no SSH transport to configure in the protocol, no `ssh` command to launch, and no nested Codex CLI process to start**.

Before repository work, execution must be under OS user `gpt`:

- `id -un` must report `gpt`;
- `HOME` must resolve to `/home/gpt`;
- repository is `/home/gpt/projects/ah-there-it-is`;
- project Python must resolve from the repository `.venv`.

If the connected environment initially runs as another local user, use the environment's available local user-switch mechanism to enter user `gpt` before development. The switch must be non-interactive; inability to become `gpt` is a blocker.

Once running as `gpt`, treat U24 as the local development machine. Do not add an SSH/Codex supervision layer.

### Windows Git Bash through Remote Commander

Prepared by Assignment 0029 but native Windows validation is still pending.

```text
host_profile: windows-git-bash
execution_channel: remote-commander
device: <explicit device>
repo_path: /c/.../ah-there-it-is
git_bash_exe: C:\Program Files\Git\bin\bash.exe
```

Do not infer or switch execution profiles/channels inside an assignment or batch.

## Repository command prelude

Every independent command batch must establish its own environment rather than relying on previous shell state.

On U24 after becoming `gpt`:

```bash
cd /home/gpt/projects/ah-there-it-is
export PATH="$PWD/.venv/bin:$PATH"
python -c 'import os,sys; assert os.name == "posix"; print(sys.executable)'
```

The interpreter must be inside the repository venv.

## Assignment lifecycle

For an issued assignment/batch:

1. read exact immutable control/assignment bytes;
2. verify start prerequisites and clean/current main;
3. create or continue the exact issued branch according to v7;
4. preserve immutable seed history;
5. implement only assigned scope;
6. self-review full implementation diff;
7. run focused checks;
8. run the complete canonical set;
9. write/update the review record and factual status;
10. open one implementation PR;
11. own bounded CI correction loop;
12. merge with merge commit;
13. sync clean main and prove seed ancestry.

Unexpected external `main` advance after batch start is a stop condition under the issued batch rules.

## Documentation policy

Active docs should describe current truth, not replay project history.

Default reading set:

1. `AGENTS.md`;
2. issued assignment/manifest;
3. `agent-tasks/common/v7.md`;
4. only source/tests needed for the task.

Read `HANDOFF.md` for orchestration/session continuity when needed.

Do not recursively read:

- `agent-tasks/archive/`;
- completed historical assignments/reviews;
- superseded protocol generations.

Archive material is evidence, not current instruction.

## Current status

Completed:

- product stages through Stage 26;
- Assignments 0001–0029;
- write-target safety, atomic turns/receipts, crash-safe idempotency;
- bounded reads/context;
- trace privacy;
- restore rehearsal;
- historical Event evidence and Activity;
- retrieval robustness baseline and candidate-starvation correction;
- location truth / sold / reactivation / portable-v2;
- Windows Git Bash host preparation.

Current protocol generation: v7.

## Next product decision gate

Before partial-quantity operations or Item split/merge behavior, explicitly decide the physical-instance/quantity model.

Current recommended direction is a hybrid:

- unique distinguishable object → separate Item;
- truly interchangeable co-located units → quantity;
- partial move/sale/disposal → explicit split into a new stable Item/group with provenance.

This recommendation is not yet an implementation authorization.

Further deferred decisions are in `agent-tasks/designs/future-decision-gates.md`.
