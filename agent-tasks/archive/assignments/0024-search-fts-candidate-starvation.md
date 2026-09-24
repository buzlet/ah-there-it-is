# Assignment 0024: bounded FTS candidate-starvation fix

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 lifecycle.

Branch: `feat/search-fts-candidate-starvation`

## Objective

Fix the measured FTS candidate-starvation defect from Assignment 0023 without changing SearchService scoring/ranking semantics or adding a new retrieval technology.

## Observed defect

The committed non-gating diagnostic for query `blue box` creates 35 prefix-matching distractors. The intended target is FTS rank 36. Current FTS candidate acquisition truncates at 20 before the existing multi-token overlap check, so the lower-ranked target is never inspected even though the earlier distractors are later rejected.

## Required behavior

- Preserve all existing public match types, numeric scores and final deterministic ordering rules.
- Preserve exact/name/alias/tag/attribute candidate acquisition behavior.
- Change only the bounded FTS candidate acquisition/overscan boundary so post-fetch overlap rejection cannot trivially starve a lower-ranked valid multi-token candidate.
- FTS scanning must remain explicitly bounded.
- Use a deterministic overscan budget with:
  - minimum scan budget >=100 rows for ordinary small limits;
  - no reduction of the existing candidate budget for larger requested limits;
  - explicit hard maximum <=500 FTS rows per search request.
- A single bounded query is preferred over iterative round trips when practical. If chunking is used, the number of chunks/rows must have an explicit hard bound.
- The existing `_fts_overlap_ok` semantics may be reused; do not weaken it merely to pass the diagnostic.
- The committed candidate-starvation diagnostic must become gating and the intended target must appear within the requested top five.
- The existing 86/86 gating corpus must remain 86/86.
- Existing target-scale structural query-count expectations must remain bounded.

## Non-goals

No fuzzy/edit-distance search, transliteration, stemming/morphology, embeddings/vector search, score changes, write-resolution/authorization changes, schema migration, provider/model work, or dependency addition.

## Focused verification

Run retrieval evaluator + focused SearchService/scale tests, then the canonical verification set.
