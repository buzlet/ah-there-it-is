# Assignment 0050: bounded database-doctor diagnostics

## Objective

Make database doctor memory use structurally bounded by sample limits for large corruption sets while preserving exact violation counts.

Current doctor truncates displayed samples to 20, but some checks first materialize complete tables or complete violation-ID lists in Python.

## Requirements

For normalized-name, blank-name, duplicate-identity, scalar state/quantity/location truth and FTS diagnostics:
- preserve exact total `count`;
- retain at most `_SAMPLE_LIMIT` sample identifiers/messages per check;
- do not build an unbounded Python list of every violation solely to later truncate it;
- where practical, use SQL counts/projections or streaming row iteration;
- preserve warning/error classification exactly;
- keep doctor read-only, including with active WAL;
- keep category/location cycle detection correct; it may retain hierarchy state needed for cycle analysis, but violation samples themselves remain bounded.

Do not change repair authorization: only derived FTS repair remains writable.

## Scale tests

Create thousands of corrupt rows efficiently and assert:
- exact counts;
- sample tuples <= 20;
- deterministic sample ordering;
- no full violation list retained by helper contracts;
- healthy target-scale DB still passes;
- doctor does not mutate main/WAL/authoritative tables;
- repair behavior unchanged.

Prefer structural instrumentation over memory/timing thresholds.

## Constraints

No new repair types, no auto-repair, no schema/index changes.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_database_doctor.py
just compile
git diff --check
```
Then commit checkpoint 0050.
