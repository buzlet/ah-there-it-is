# 0063 — internal split and partial move/take

## Objective

Implement homogeneous-lot splitting as an internal atomic primitive and use it for partial move/take operations without exposing low-level split orchestration to the LLM.

## Portion representation

The high-level service must distinguish:

- no portion supplied => whole Item;
- exact N => a known exact subset;
- approximate N => an approximate subset;
- unknown => an unspecified nonempty subset.

Do not overload null so that "whole Item" and "unknown partial subset" become indistinguishable.

## Split semantics

On a true split:

- source/remainder keeps its stable ID;
- child receives a new stable ID;
- copy name, description/comment, category, aliases, tags, attributes, state and initial location truth;
- quantity is derived, not blindly copied;
- provenance is recorded through structured Events so both source and child history can identify the relationship without a lineage table;
- split plus requested move/take is one transaction.

No merge is implemented.

## Arithmetic

Required behavior:

- exact 20 minus exact 5 => source exact 15, child exact 5;
- approximate 20 minus exact 5 => source approximate 15, child exact 5;
- approximate 20 minus approximate 5 => source approximate 15, child approximate 5;
- unknown source minus exact/approximate subset => source remains unknown, child keeps the stated subset precision;
- unknown partial subset => child unknown; source becomes/remains unknown;
- approximate subtraction with remainder <= 0 => source unknown, never zero/negative;
- exact source plus an exact subset equal to the known total may be treated as a whole operation preserving the existing ID;
- if a new explicit subset fact contradicts a smaller recorded exact total, preserve the requested child fact and degrade the uncertain remainder rather than storing impossible arithmetic; surface this through result/receipt evidence.

Do not infer removed state from arithmetic.

## Partial move/take

- Whole move/take keeps existing behavior and stable ID.
- Partial move: split then move child.
- Partial take: split then mark child in_use.
- Failure after split must roll back source quantity, child creation and all Events.

## Comment handling

Copied comments are not rewritten automatically in this task. Return enough structured result data for the agent layer to detect a potentially contradictory copied comment later.

## Focused verification

Create tests/test_quantity_split.py.

    .venv/bin/python -m pytest -q tests/test_quantity_split.py tests/test_domain.py -k "split or partial or move or take"
    just compile
    git diff --check
