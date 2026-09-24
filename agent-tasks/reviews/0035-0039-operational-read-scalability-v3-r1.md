# Batch review: operational read scalability v3

## Provenance

- Batch: `post-0034-operational-read-scalability-v3-2026-09-24`
- Control: `efbe3eb39bd2e75c194e036735666be0bbfad584`
- Start main: `1937abe8bc2096175112927af8f2d67e97e516c5`
- Seed: `9649c299b40a06eb18d1bd5fabb07a84da6f6e51`
- Branch: `feat/operational-read-scalability-v3`

## Task checkpoints

### 0035 — bounded conversation history

- Range: `9649c299b40a06eb18d1bd5fabb07a84da6f6e51..dbfca0a3e6b882c13f57c331f3aeee51f1002fc1`
- Focused: `python -m pytest -q tests/test_conversation_context.py tests/test_app.py -k "conversation or chat"` — 13 passed.
- `just compile` and `git diff --check` — passed.
- Corrections: 1; self-review added conversation ownership validation for positive message cursors.

### 0036 — scalable evaluation reads

- Range: `dbfca0a3e6b882c13f57c331f3aeee51f1002fc1..6de1a82b7325c27a70a1017998714b4b6f5fe458`
- Focused: `python -m pytest -q tests/test_evaluation.py tests/test_app.py -k "evaluation or feedback"` — 12 passed.
- `just compile` and `git diff --check` — passed.
- Corrections: 0.

### 0037 — scalable experiment reads

- Range: `6de1a82b7325c27a70a1017998714b4b6f5fe458..d3119a102d6c799e7aecc7b7d09c26c058d34992`
- Focused: `python -m pytest -q tests/test_experiments.py tests/test_app.py -k "experiment"` — 9 passed.
- `just compile` and `git diff --check` — passed.
- Corrections: 1; self-review strengthened deterministic ordering and asserted a single summary query.

### 0038 — paged chat-request audit

- Range: `d3119a102d6c799e7aecc7b7d09c26c058d34992..4246c532fedf523025347f1ab90f2b1efc2f9e0d`
- Focused: `python -m pytest -q tests/test_idempotency.py tests/test_app.py -k "chat_request or recovery or idempot"` — 20 passed.
- `just compile` and `git diff --check` — passed.
- Corrections: 2; repaired response-helper placement and added route-level pagination/validation coverage.

### 0039 — operational-history scale regression

- Range: `4246c532fedf523025347f1ab90f2b1efc2f9e0d..6bf9ddb126c44562d2da40107766b8e1ba05dce6`
- Focused: `python -m pytest -q tests/test_operational_history_scale.py` — 4 passed.
- `just compile` and `git diff --check` — passed.
- Corrections: 0.

## Cumulative self-review

- Correction commit: `a08f058dff657abce0f9bd2daf57772fae5eefa9` updates three stale test-only callers to the bounded conversation window discovered by the final source audit.
- Conversation restore is ID-cursor based, bounded to `limit + 1`, and annotates only returned assistant messages.
- Evaluation summaries use SQL aggregation/projection and run lists load one bounded page.
- Experiment summaries stream scalar rows across all history with no 10,000-row cap or source-run ORM graph materialization.
- Chat-request list/page reads use a self-join projection, preserving API shape without recovery-source N+1 queries.
- Deterministic 1,000-row fixtures prove bounded rows, query counts/identity maps, navigation, cursor stability, all-time summaries, and no Event mutation.
- No schema/index, dependency, provider, ranking, retention, inventory, or CI workflow changes.

## Final local verification

- Combined manifest integration set — 55 passed.
- Wheel template/static/runtime focused set — 1 passed.
- `just compile` — passed.
- `git diff --check` — passed.
- Repository-wide local regression was not run (`full_local_required: false`).

## PR, CI, and merge

- One PR and its exact-head authoritative CI are required after this review commit.
- Final PR URL/head, CI result, merge SHA, final main, and seed ancestry proof are reported by the completing agent after merge.

## Deviations and blockers

- Seed creation required a direct Git-object file copy after the patch mechanism twice failed to materialize new files; every destination blob was verified against the immutable control SHA before the seed commit.
- Initial seed commit attempt stopped because repository-local Git identity was absent; staged state was inspected per protocol, canonical author identity was configured only in this checkout, and the seed was committed once without rewrite.
- No blockers remain.
