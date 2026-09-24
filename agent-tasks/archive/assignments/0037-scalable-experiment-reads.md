# Assignment 0037: scalable experiment reads

## Objective

Remove the experiment dashboard's fixed 10,000-run summary truncation and avoid materializing heavy ExperimentRun/source-run ORM graphs when computing aggregate summaries.

Preserve current metrics exactly.

## Run list pagination

Add a typed experiment run page:

- default page size 50;
- maximum 100;
- deterministic newest-first order;
- total/previous/next metadata;
- review/source feedback loading only for returned page rows.

Update `/experiments` with page/page_size navigation.

## Summary projection

Current `ExperimentService.summaries()` calls `recent_runs(limit=10_000)`, which silently excludes older runs and eagerly loads source AgentRunLog objects.

Replace this with a dedicated scalar/projection query over only fields needed by the summary:

ExperimentRun:

- experiment name;
- prompt version/hash;
- provider/model/config;
- status;
- rounds;
- final content needed by clarification heuristic;
- tool trace needed by existing tool/mutation error heuristics.

Joined scalar data:

- source run feedback rating;
- experiment review choice;
- variant rating.

Do not load full source AgentRunLog traces/messages/config objects.

Process results in bounded chunks/streaming where supported rather than building a 10,000-object ORM graph.

Remove the arbitrary 10,000 summary cap: summaries represent all stored experiment runs.

Preserve:

- completed/diverged/failed counts;
- average rounds;
- source and variant average ratings;
- review outcome counts;
- clarification rate;
- tool-error rate;
- mutation-error rate;
- canonical config grouping/hash;
- deterministic sort.

## Tests

Cover:

- paged runs and invalid page sizes;
- summary metrics unchanged;
- source feedback/review semantics;
- all rows beyond the former 10,000 boundary contribute to summary using efficient bulk test setup;
- summary execution does not populate the Session identity map with all ExperimentRun/AgentRunLog rows;
- no N+1 source-run loading;
- detail/review endpoints unchanged.

## Constraints

No change to experiment heuristic definitions, review choices, trace retention or provider behavior.

## Checkpoint

Run only the 0037 focused checks from the manifest, then commit the 0037 checkpoint.
