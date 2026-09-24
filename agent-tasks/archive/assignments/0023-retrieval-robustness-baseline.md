# Assignment 0023: offline retrieval robustness baseline

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/retrieval-robustness-baseline`

## Objective

Create a deterministic offline measurement surface for real-world RU/UK/EN inventory queries so future search changes are driven by evidence rather than intuition.

This assignment establishes measurement. It does not introduce fuzzy matching, transliteration, stemming, embeddings or provider reasoning.

## Required behavior

- Add a hand-authored versioned retrieval evaluation corpus under `eval/` with at least 60 cases total and meaningful RU, UK and EN coverage.
- Use a deterministic fixture/inventory referenced by stable semantic labels; do not rely on production/private data.
- Cover at minimum:
  - canonical names;
  - aliases;
  - punctuation/separator variants already intended to normalize;
  - apostrophe variants relevant to Ukrainian text;
  - mixed multi-token queries;
  - tags;
  - structured attributes;
  - ambiguous duplicate names;
  - no-match cases.
- Every case must state an explicit expectation such as:
  - target entity expected in top N;
  - expected ambiguity set;
  - expected no result;
  - accepted match-type class where relevant.
- Add an offline evaluator command/module and a Just recipe producing a machine-readable JSON report with:
  - total/pass/fail;
  - per-language totals;
  - per-case result IDs/match types/scores;
  - failure reasons.
- Add one adversarial **candidate-starvation diagnostic** fixture with many distractors and a multi-token target. Measure whether the current bounded retrieval pool still returns the intended target.
- The committed gating corpus must pass with current intended SearchService semantics. Cases documenting desirable but unsupported typo/transliteration/inflection behavior belong in a separate non-gating `observations` section/report and must not be silently declared requirements.
- Do not change SearchService ranking, normalization or candidate acquisition in this assignment merely to improve the new score. If a current documented invariant is demonstrably violated, stop and report the blocker rather than broadening scope.
- Add the offline gating evaluator to canonical development verification through a Just recipe, but do **not** add a separate GitHub Actions job; the existing single application CI job should invoke the recipe as part of its normal sequence only if updating the canonical recipe set is required.
- Document the measured baseline and explicitly list unsupported query classes observed, without recommending embeddings absent evidence.

## Constraints

No fuzzy/edit-distance matching, transliteration, stemming/morphology library, embeddings/vector DB, provider/model calls, search-rank changes, schema migration, dependency upgrade or new CI job.

## Focused verification

Run the retrieval evaluator and focused SearchService/eval tests, then the canonical project verification set including the new retrieval check.
