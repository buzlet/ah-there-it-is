# Batch manifest: operational read scalability v4

Batch ID: `post-0034-operational-read-scalability-v4-2026-09-24`

Protocol: `agent-tasks/common/v8.md`

Expected start main:

`471fc313ec532371e860f1a72ba38544b5a9376e`

Implementation branch:

`feat/operational-read-scalability-v4`

Execution user:

`rdu01`

Required work directory:

`/home/rdu01/projects/operational-read-scalability-0035-0039-v4`

Batch review destination:

`agent-tasks/reviews/0035-0039-operational-read-scalability-v4-r1.md`

Full local regression:

`full_local_required: false`

## Execution startup preflight — run once

The direct shell is already running as OS user `rdu01`.

Do not use `sudo`, `su`, or switch users.

If the work directory does not yet contain a checkout, create a fresh checkout there from the canonical repository remote.

Before the first repository mutation, perform this preflight exactly once:

```bash
test "$(id -un)" = "rdu01"
test "$HOME" = "/home/rdu01"
cd /home/rdu01/projects/operational-read-scalability-0035-0039-v4 || exit 1
test "$(git rev-parse --show-toplevel)" = "/home/rdu01/projects/operational-read-scalability-0035-0039-v4"
export PATH="$PWD/.venv/bin:$PATH"
python -c 'import os,sys; assert os.name == "posix"; print(sys.executable)'
```

If `.venv` is absent, create/install the normal project development environment in this checkout, then complete the startup preflight.

Do not repeat the full user/HOME/Git-toplevel preflight before edits, tests, commits or other mutations.

## Later shell commands

For every later independent shell invocation, use only:

```bash
cd /home/rdu01/projects/operational-read-scalability-0035-0039-v4 || exit 1
export PATH="$PWD/.venv/bin:$PATH"
<command>
```

Repeat the full startup preflight only after an actual execution-session reset/reconnect or after concrete evidence that the working-directory/repository context was lost.

Do not use another checkout, including prior v1/v2/v3 patch directories.

## Objective

Bound operational/history read paths that can grow indefinitely during normal application use, without changing inventory/domain semantics.

Current gaps:
- unbounded persisted conversation history restore;
- unbounded conversation-run annotation;
- evaluation summaries materializing all AgentRunLog ORM rows;
- experiment summaries materializing up to 10,000 heavy ExperimentRun/source objects and truncating beyond that;
- fixed 100/200 operational list ceilings without navigation;
- chat-request recovery-source N+1 lookup;
- no operational-history scale regression fixture.

## Ordered tasks

1. 0035 — bounded conversation history
2. 0036 — scalable evaluation reads
3. 0037 — scalable experiment reads
4. 0038 — paged chat-request audit
5. 0039 — operational-history scale regression

Task specs:
- `agent-tasks/batches/post-0034-operational-read-scalability-v4/0035-bounded-conversation-history.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v4/0036-scalable-evaluation-reads.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v4/0037-scalable-experiment-reads.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v4/0038-paged-chat-request-audit.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v4/0039-operational-history-scale.md`

Seed destinations:
- `agent-tasks/assignments/0035-bounded-conversation-history.md`
- `agent-tasks/assignments/0036-scalable-evaluation-reads.md`
- `agent-tasks/assignments/0037-scalable-experiment-reads.md`
- `agent-tasks/assignments/0038-paged-chat-request-audit.md`
- `agent-tasks/assignments/0039-operational-history-scale.md`

The single batch seed commit must contain exact copies of this manifest and all five task specs in their active destinations.

## Focused checkpoints

0035:
```text
python -m pytest -q tests/test_conversation_context.py tests/test_app.py -k "conversation or chat"
just compile
git diff --check
```

0036:
```text
python -m pytest -q tests/test_evaluation.py tests/test_app.py -k "evaluation or feedback"
just compile
git diff --check
```

0037:
```text
python -m pytest -q tests/test_experiments.py tests/test_app.py -k "experiment"
just compile
git diff --check
```

0038:
```text
python -m pytest -q tests/test_idempotency.py tests/test_app.py -k "chat_request or recovery or idempot"
just compile
git diff --check
```

0039:
```text
python -m pytest -q tests/test_operational_history_scale.py
just compile
git diff --check
```

## Final local integration checks

Run exactly:

```text
python -m pytest -q \
  tests/test_conversation_context.py \
  tests/test_evaluation.py \
  tests/test_experiments.py \
  tests/test_idempotency.py \
  tests/test_app.py \
  tests/test_operational_history_scale.py
python -m pytest -q tests/test_wheel_migrations.py -k "template or static or runtime"
just compile
git diff --check
```

Do not run repository-wide `just check` locally.

## Mutation failure rule

After any failed file-changing command:

1. do not retry the same mutation immediately;
2. inspect `git status --short`, `git diff`, and `git diff --cached`;
3. inspect the target's current state;
4. construct a new edit from the actual state.

After two failures of one logical edit strategy, abandon it and use a simpler direct-edit strategy.

Do not replay the same `git apply`/base64 payload with quoting changes.

## Scope constraints

No quantity/physical-instance semantics, Item split/merge, schema/index migration, retrieval/ranking changes, provider/model behavior changes, retention policy, backup automation, auth/multi-user, hard delete/undo, dependency upgrade or CI workflow change.

If a schema/index change becomes necessary, stop and report a blocker.

## Final lifecycle

After 0039:
- cumulative self-review;
- single batch review;
- final integration checks only;
- one PR;
- one authoritative exact-head CI;
- narrow CI correction loop;
- merge commit after green head;
- clean main sync and seed ancestry proof.

Return one compact batch report.
