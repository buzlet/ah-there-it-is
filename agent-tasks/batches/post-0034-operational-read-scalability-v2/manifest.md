# Batch manifest: operational read scalability v2

Batch ID: `post-0034-operational-read-scalability-v2-2026-09-24`

Protocol: `agent-tasks/common/v8.md`

Expected start main:

`eac461ab1ec1dafc81c058df7a15a23e77ff7096`

Implementation branch:

`feat/operational-read-scalability-v2`

Required execution user:

`rdu1`

Required work directory:

`/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`

Batch review destination:

`agent-tasks/reviews/0035-0039-operational-read-scalability-v2-r1.md`

Full local regression:

`full_local_required: false`

## Execution invariant

The environment is already connected to U24 and commands are executed as OS user `rdu1`.

Do not use `sudo`, `su`, another OS user, or another repository checkout.

Every Git, edit, Python, Just and test operation for this batch must happen inside exactly:

`/home/rdu1/Projects/operational-read-scalability-0035-0039-v2`

Before mutation, verify:

```bash
test "$(id -un)" = "rdu1"
test "$HOME" = "/home/rdu1"
test "$PWD" = "/home/rdu1/Projects/operational-read-scalability-0035-0039-v2"
test "$(git rev-parse --show-toplevel)" = "/home/rdu1/Projects/operational-read-scalability-0035-0039-v2"
```

If the work directory does not yet contain a checkout, create a fresh checkout there from the canonical repository remote, then remain in that checkout for the complete batch.

Do not reuse:
- `/home/gpt/projects/ah-there-it-is`;
- another path under `/home/rdu1/Projects`;
- a previous patch checkout.

Every independent command batch starts with:

```bash
cd /home/rdu1/Projects/operational-read-scalability-0035-0039-v2
export PATH="$PWD/.venv/bin:$PATH"
```

If the repository-local `.venv` does not exist, create it in this workdir and install the normal development environment before tests.

## Objective

Bound operational/history read paths that can grow indefinitely during normal application use, without changing inventory/domain semantics.

Current observed gaps:

- full persisted conversation history is loaded for browser restore;
- conversation run annotation loads every run for that conversation;
- evaluation summaries materialize all AgentRunLog ORM objects;
- experiment summaries materialize up to 10,000 heavy ExperimentRun/source objects and silently truncate beyond that;
- evaluation/experiment HTML lists use fixed recent limits without navigation;
- chat-request HTML audit uses a fixed 200-row list and performs per-row recovery-source lookup;
- target-scale structural regression currently focuses inventory data rather than growing operational history.

## Ordered tasks

1. 0035 — bounded conversation history
2. 0036 — scalable evaluation reads
3. 0037 — scalable experiment reads
4. 0038 — paged chat-request audit
5. 0039 — operational-history scale regression

Task specs:

- `agent-tasks/batches/post-0034-operational-read-scalability-v2/0035-bounded-conversation-history.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v2/0036-scalable-evaluation-reads.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v2/0037-scalable-experiment-reads.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v2/0038-paged-chat-request-audit.md`
- `agent-tasks/batches/post-0034-operational-read-scalability-v2/0039-operational-history-scale.md`

Seed destinations:

- `agent-tasks/assignments/0035-bounded-conversation-history.md`
- `agent-tasks/assignments/0036-scalable-evaluation-reads.md`
- `agent-tasks/assignments/0037-scalable-experiment-reads.md`
- `agent-tasks/assignments/0038-paged-chat-request-audit.md`
- `agent-tasks/assignments/0039-operational-history-scale.md`

The single batch seed commit must contain exact copies of this manifest and all five task specs in their active destinations.

## Task checkpoints

### 0035
```text
python -m pytest -q tests/test_conversation_context.py tests/test_app.py -k "conversation or chat"
just compile
git diff --check
```

### 0036
```text
python -m pytest -q tests/test_evaluation.py tests/test_app.py -k "evaluation or feedback"
just compile
git diff --check
```

### 0037
```text
python -m pytest -q tests/test_experiments.py tests/test_app.py -k "experiment"
just compile
git diff --check
```

### 0038
```text
python -m pytest -q tests/test_idempotency.py tests/test_app.py -k "chat_request or recovery or idempot"
just compile
git diff --check
```

### 0039
```text
python -m pytest -q tests/test_operational_history_scale.py
just compile
git diff --check
```

## Final local integration checks

Run exactly:

```text
python -m pytest -q   tests/test_conversation_context.py   tests/test_evaluation.py   tests/test_experiments.py   tests/test_idempotency.py   tests/test_app.py   tests/test_operational_history_scale.py
python -m pytest -q tests/test_wheel_migrations.py -k "template or static or runtime"
just compile
git diff --check
```

Do not run repository-wide `just check` locally. Final PR CI is the repository-wide regression gate.

## Mutation-failure circuit breaker

After any failed file-changing command:

1. do not retry the same mutation immediately;
2. inspect `git status --short`, `git diff`, and `git diff --cached`;
3. inspect the target file/current state;
4. construct a new operation from current state.

After two failures of the same logical edit strategy, abandon that strategy and use a simpler direct file-edit approach.

Never repeatedly replay the same `git apply`/base64 patch with only quoting changes.

## Scope constraints

No quantity/physical-instance semantics, Item split/merge, schema/index migration, retrieval/ranking change, provider/model behavior change, retention policy, automated backup policy, authentication/multi-user work, hard delete/undo, dependency upgrade or CI workflow change.

If a schema/index change appears necessary, stop and report it as a blocker.

## Final lifecycle

After all five checkpoints:

- cumulative seed..HEAD self-review;
- single batch review;
- only final integration checks above;
- one PR;
- bounded exact-head CI observation;
- narrow reproduction + affected focused checks for CI corrections;
- merge commit only after final exact head is green;
- sync clean main and prove seed ancestry.

Return one compact batch report.
