# Batch manifest: operational read scalability

Batch ID: `post-0034-operational-read-scalability-2026-09-24`

Protocol: `agent-tasks/common/v8.md`

Expected start main:

`d63acfee8b2636753a7869c746057e1283c46b79`

Implementation branch:

`feat/operational-read-scalability`

Batch review destination:

`agent-tasks/reviews/0035-0039-operational-read-scalability-r1.md`

Full local regression:

`full_local_required: false`

## Execution

This batch is intended for the transparent U24 direct-shell channel.

The interactive environment initially logs in as OS user:

`RDU1`

`RDU1` has passwordless/non-interactive sudo available for this work.

All repository/Git/Python/Just/test operations must run as OS user:

`gpt`

Do not perform repository work as RDU1.

For every independent command batch, use the logical equivalent of:

```bash
sudo -n -u gpt -H bash -lc '
  cd /home/gpt/projects/ah-there-it-is
  export PATH="$PWD/.venv/bin:$PATH"
  <commands>
'
```

Before mutation verify inside that gpt shell:

```bash
id -un
printf '%s\n' "$HOME"
pwd
python -c 'import os,sys; assert os.name == "posix"; print(sys.executable)'
```

Required facts:

- user: `gpt`;
- HOME: `/home/gpt`;
- repo: `/home/gpt/projects/ah-there-it-is`;
- Python executable: repository `.venv`.

If `sudo -n -u gpt -H ...` cannot run non-interactively, stop with an infrastructure blocker. Do not modify repo ownership or continue as RDU1.

There is no SSH setup and no nested Codex process.

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

- `agent-tasks/batches/post-0034-operational-read-scalability/0035-bounded-conversation-history.md`
- `agent-tasks/batches/post-0034-operational-read-scalability/0036-scalable-evaluation-reads.md`
- `agent-tasks/batches/post-0034-operational-read-scalability/0037-scalable-experiment-reads.md`
- `agent-tasks/batches/post-0034-operational-read-scalability/0038-paged-chat-request-audit.md`
- `agent-tasks/batches/post-0034-operational-read-scalability/0039-operational-history-scale.md`

Seed destinations:

- `agent-tasks/assignments/0035-bounded-conversation-history.md`
- `agent-tasks/assignments/0036-scalable-evaluation-reads.md`
- `agent-tasks/assignments/0037-scalable-experiment-reads.md`
- `agent-tasks/assignments/0038-paged-chat-request-audit.md`
- `agent-tasks/assignments/0039-operational-history-scale.md`

The single batch seed commit must contain exact copies of this manifest and all five task specs in their active destinations.

## Task checkpoints

### 0035 focused checks

```text
python -m pytest -q tests/test_conversation_context.py tests/test_app.py -k "conversation or chat"
just compile
git diff --check
```

### 0036 focused checks

```text
python -m pytest -q tests/test_evaluation.py tests/test_app.py -k "evaluation or feedback"
just compile
git diff --check
```

### 0037 focused checks

```text
python -m pytest -q tests/test_experiments.py tests/test_app.py -k "experiment"
just compile
git diff --check
```

### 0038 focused checks

```text
python -m pytest -q tests/test_idempotency.py tests/test_app.py -k "chat_request or recovery or idempot"
just compile
git diff --check
```

### 0039 focused checks

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

Do not run repository-wide `just check` locally. `full_local_required` is false; final PR CI is the repository-wide regression gate.

## Scope constraints

No:

- inventory quantity/physical-instance semantics;
- Item split/merge;
- schema migration or new database index;
- retrieval/ranking changes;
- provider/model behavior changes;
- trace retention/deletion policy;
- automated backup policy;
- authentication/multi-user work;
- hard delete/undo;
- dependency upgrades;
- CI workflow changes.

If a schema/index change appears necessary for correctness, stop and report it as a design blocker rather than adding it.

## Final lifecycle

After all five task checkpoints:

- perform cumulative seed..HEAD self-review;
- write the single batch review;
- run only the final local integration checks above;
- open one PR;
- use bounded exact-head CI observation;
- fix CI failures with narrow reproduction + affected focused checks only;
- merge only after exact final PR head CI is green;
- merge with merge commit;
- sync clean main and prove seed ancestry.

After merge return one compact batch report.
