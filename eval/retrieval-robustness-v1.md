<!-- eval/retrieval-robustness-v1.md -->
# Offline retrieval robustness baseline v1

## Scope

- The versioned corpus is retrieval-robustness-v1 in retrieval-robustness-v1.json.
- Its synthetic fixture is deterministic and uses semantic labels; it contains no production or private inventory data.
- The 86 gating cases cover English, Russian and Ukrainian canonical names, aliases, separator variants, Ukrainian apostrophe forms, mixed-token queries, tags, structured attributes, duplicate-name ambiguity and no-match expectations.
- Each case states a top-N target with accepted match types, an exact ambiguity set, or an expected empty result.
- The evaluator calls the current SearchService offline. It does not call a provider and does not modify search ranking, normalization or candidate acquisition.
- just retrieval-eval writes a machine-readable report with totals, per-language totals, semantic labels and result IDs, match types, scores, and failure reasons. The same recipe is part of the existing application CI job.

## Measured gating baseline

- English: 28/28 passed.
- Russian: 27/27 passed.
- Ukrainian: 31/31 passed.
- Total: 86/86 passed; 0 failures.

## Candidate-starvation diagnostic

The separate non-gating fixture has 35 prefix-matching distractors and one multi-token target for query “blue box”. The current limit=5 search uses an FTS candidate limit of 20. The target ranks 36th in the expanded FTS diagnostic and is absent from the bounded result, so the diagnostic reports candidate starvation. It does not affect gating totals.

## Non-gating observations

These observations are reported separately from the gating corpus.

| Language | Query class | Query | Observed |
| --- | --- | --- | --- |
| English | Typo | ThnkPad T14 | Target not returned |
| Russian | Latin transliteration | multimetr | Target not returned |
| Ukrainian | Inflection | маршрутизатора | Target not returned |
| Ukrainian | U+02BC apostrophe | Обʼєктив Helios 44 2 | Target surfaced through FTS; the separator normalizer retains U+02BC as a word character |

These observations remain outside the gating totals. This baseline makes no recommendation about embeddings.
