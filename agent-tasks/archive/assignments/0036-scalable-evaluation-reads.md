# Assignment 0036: scalable evaluation reads

## Objective

Make the evaluation dashboard scale with accumulated AgentRunLog history without loading all heavy run ORM objects/traces into memory.

Preserve evaluation summary semantics.

## Run list pagination

Add a typed evaluation run page.

Requirements:

- default page size 50;
- maximum 100;
- deterministic newest-first order;
- total/previous/next metadata;
- bounded ORM load for one page;
- feedback eager loading only for returned rows.

Update `/evaluations` to accept page/page_size and render previous/next navigation.

Do not silently keep a fixed "latest 100" UI ceiling.

## Summary aggregation

Current `EvaluationService.summaries()` materializes all AgentRunLog rows including heavy JSON trace fields.

Replace with SQL-level aggregation/projection.

Preserve grouping semantics by:

- prompt version;
- prompt hash;
- provider;
- model;
- canonicalized sanitized LLM config.

Because historical JSON serialization order may differ, it is acceptable to:

1. aggregate in SQL by the raw stored config representation plus scalar grouping fields;
2. canonicalize returned aggregate groups in Python;
3. merge aggregate groups that canonicalize to the same config identity using weighted counts/sums.

The result must preserve:

- total runs;
- rated runs;
- average rating;
- config hash;
- deterministic sort order.

Do not load input_messages/tool_trace/final_content just to compute summaries.

## Tests

Cover:

- > page-size run history and navigation;
- page bounds and invalid values;
- all-time summary counts remain correct across multiple pages;
- rated/unrated weighted averages;
- logically equivalent config dictionaries still group together;
- heavy trace fields are not required/materialized by summaries;
- query count/loaded ORM objects remain bounded relative to number of summary groups, not number of runs;
- existing detail and feedback behavior unchanged.

## Constraints

No schema migration, retention policy, rating semantics or provider metadata contract change.

## Checkpoint

Run only the 0036 focused checks from the manifest, then commit the 0036 checkpoint.
