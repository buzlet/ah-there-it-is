# Batch manifest: streaming evaluation export

Batch ID: `post-0039-streaming-evaluation-export`

Protocol: `agent-tasks/common/v8.md`

Expected start main:

`821910c1db1a65f06f3184321baa8683a1a87402`

Implementation branch:

`feat/streaming-evaluation-export-0040`

Execution user:

`rdu01`

Required work directory:

`/home/rdu01/projects/streaming-evaluation-export-0040`

Batch review destination:

`agent-tasks/reviews/0040-streaming-evaluation-export-r1.md`

Full local regression:

`full_local_required: false`

## Task

Only:

`0040 — streaming evaluation export`

Exact control spec:

`agent-tasks/batches/post-0039-streaming-evaluation-export/0040-streaming-evaluation-export.md`

Seed destination:

`agent-tasks/assignments/0040-streaming-evaluation-export.md`

The batch seed commit must contain exact copies of this manifest and the 0040 assignment at the active destinations.

## Execution

Work only as `rdu01` and only inside:

`/home/rdu01/projects/streaming-evaluation-export-0040`

Do not use sudo/su or another checkout.

If the checkout does not exist, create it fresh at the exact path from the canonical repository.

Follow the current v8 execution checks.

For normal independent command calls, the repository command prefix contains only the exact work-directory change:

```bash
cd /home/rdu01/projects/streaming-evaluation-export-0040 || exit 1
```

Do not add:

```bash
export PATH="$PWD/.venv/bin:$PATH"
```

Direct Python commands use `.venv/bin/python`.

Just recipes use `just`; the repository Justfile supplies the local venv PATH.

## Focused checkpoint

Run exactly:

```text
.venv/bin/python -m pytest -q tests/test_evaluation.py tests/test_evaluation_export.py
just compile
git diff --check
```

## Final local integration

Because this batch has one task, after the checkpoint/cumulative self-review run exactly the same focused set once as the final local integration proof:

```text
.venv/bin/python -m pytest -q tests/test_evaluation.py tests/test_evaluation_export.py
just compile
git diff --check
```

Do not run repository-wide `just check` locally.

Final PR CI is the authoritative repository-wide regression.

## Mutation failure rule

After a failed file-changing command, inspect current `git status --short`, `git diff`, `git diff --cached`, and target contents before constructing a new edit.

Do not repeatedly replay the same failed patch transport with quoting changes.

## Final lifecycle

- one batch seed;
- implement 0040;
- focused checkpoint;
- cumulative self-review;
- one batch review;
- final focused integration proof;
- one PR;
- one authoritative exact-head CI;
- narrow correction loop if needed;
- merge commit after green CI;
- clean main sync and seed ancestry proof.

Return one compact batch report.
