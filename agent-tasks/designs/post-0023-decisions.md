# Decisions after Assignment 0023

Date: 2026-09-24

## Retrieval

- Gating corpus: 86/86 pass.
- Existing intended ranking/normalization remains accepted.
- Measured defect: bounded candidate starvation with target FTS rank 36 outside the current pool of 20.
- Decision: fix candidate acquisition only; do not add fuzzy/transliteration/morphology/embeddings.
- Assignment 0024 delivered bounded FTS overscan (100–500 rows); the `blue box` rank-36 candidate is now a gating top-five success.
  Scoring, ordering and candidate sources remain unchanged.

## CI coverage

PR #42 measured 84% branch coverage:
- 6041 statements;
- 853 missed;
- 1516 branches;
- 293 partial branches.

Decision: keep report-only coverage for now. No `fail-under` yet.

## Stage 26 gates closed

Approved:
- portable-v2 with v1 import compatibility;
- explicit reactivation for sold/discarded with caller-selected non-terminal state and known/unknown location truth;
- terminal Items remain searchable;
- browser catalog defaults active-only with terminal/all filters;
- user-facing labels distinguish condition/state unknown from location unknown.

With these decisions encoded, Stage 26 implementation no longer requires a product-policy pause.
