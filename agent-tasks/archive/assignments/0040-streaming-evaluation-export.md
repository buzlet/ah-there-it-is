# Assignment 0040: streaming evaluation export

## Objective

Make rated-run evaluation export complete and memory-bounded without changing its external JSON record contract.

Current implementation in `src/ah_there_it_is/evaluation_export.py`:

- calls `EvaluationService.recent_runs(limit=100_000)`;
- therefore silently omits rated runs beyond that ceiling;
- materializes full `AgentRunLog` ORM objects;
- builds the complete exported record list in memory before writing JSON.

Replace that path with a streaming/projection implementation.

No inventory/domain semantics change.

## External compatibility

Keep the existing invocation:

```bash
python -m ah_there_it_is.evaluation_export
```

The command still writes one valid JSON array to stdout and a trailing newline.

Preserve the existing per-record keys and meanings exactly:

- `run_id`
- `conversation_id`
- `prompt_version`
- `prompt_hash`
- `system_prompt`
- `llm_provider`
- `llm_model`
- `llm_config`
- `input_messages`
- `tool_trace`
- `final_content`
- `rounds`
- `status`
- `error`
- `rating`
- `comment`
- `created_at`

Do not add or remove fields in this assignment.

Preserve logical ordering: oldest qualifying run first, matching the current reversed-descending export behavior.

Only completed runs with feedback are exported, matching current behavior.

Empty export remains:

```json
[]
```

plus the normal trailing newline.

Byte-for-byte whitespace compatibility is not required; parsed JSON semantics are.

## Read projection

Introduce a dedicated export projection/iterator owned by the evaluation read layer rather than reusing dashboard page methods.

Requirements:

- no arbitrary total-row limit;
- deterministic `AgentRunLog.id ASC` order;
- join feedback in the same read path;
- select only columns required by the export record;
- do not instantiate one `AgentRunLog` + feedback ORM graph per historical row;
- do not populate the Session identity map proportionally to export size;
- use bounded/chunked result iteration where SQLAlchemy supports it;
- no N+1 queries.

A small typed immutable projection/dataclass is preferred over anonymous positional tuples.

Do not change `rated_runs()` semantics merely to serve this exporter if other callers still need that bounded API.

## Streaming JSON writer

The exporter must not first construct:

```python
records = [...]
```

for the complete history.

Write the JSON array incrementally.

Separate the record iterator from the JSON writer sufficiently that streaming behavior can be tested without a real database.

The writer must:

- emit syntactically valid JSON for zero, one and many records;
- support non-ASCII text with current `ensure_ascii=False` semantics;
- request/write records incrementally rather than exhausting the iterator first;
- finish with one newline.

## Scale / structural tests

Add `tests/test_evaluation_export.py`.

Cover at minimum:

1. zero rated runs -> valid empty array;
2. rated and unrated runs -> only rated completed runs exported;
3. deterministic oldest-first ordering;
4. exact existing record-key set;
5. Unicode survives round-trip;
6. no query LIMIT/cap representing the former 100,000 ceiling;
7. a bulk history produces all qualifying rows through the projection;
8. export projection does not populate the ORM identity map proportional to row count;
9. bounded query count (no N+1);
10. writer is demonstrably lazy: a generator may assert that bytes for the first record have been written before the writer requests the next record;
11. output parses with `json.loads`.

Use efficient bulk inserts for scale tests. Do not introduce wall-clock timing thresholds.

You do not need to insert 100,001 full heavy ORM objects merely to prove the old ceiling is gone; prove absence of a SQL/result cap structurally and separately prove the writer/iterator do not impose an application-level cap.

## Just / venv behavior

This assignment is also the first implementation task after the repo-local Just venv change.

Do not run:

```bash
export PATH="$PWD/.venv/bin:$PATH"
```

For direct Python commands use:

```bash
.venv/bin/python ...
```

For Just recipes use ordinary:

```bash
just ...
```

The Justfile owns its repo-local `.venv/bin` preference.

Do not add shell activation, direnv, persistent-shell setup or other environment machinery.

## Constraints

No:

- database migration or index change;
- export schema/version change;
- new CLI flags;
- import behavior change;
- experiment replay behavior change;
- provider/model calls;
- trace retention/deletion policy;
- dependency addition;
- quantity/physical-instance semantics;
- CI workflow change.

If correctness appears to require one of these, stop and report a blocker.

## Checkpoint verification

Run exactly:

```text
.venv/bin/python -m pytest -q tests/test_evaluation.py tests/test_evaluation_export.py
just compile
git diff --check
```

Then commit the 0040 checkpoint.
