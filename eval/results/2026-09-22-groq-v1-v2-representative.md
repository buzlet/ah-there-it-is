# Groq representative prompt comparison — 2026-09-22

This is a descriptive Stage 6 evidence record, not a prompt ranking.

## Provenance

- Corpus: `inventory-corpus-v1`
- Fixture: `inventory-fixture-v1`
- Provider: `groq`
- Model: `qwen/qwen3.8-27b`
- Provider-config SHA-256: `61a0a9857af0a1a2d95af799a6d9c6d4047f9c7991786a4406773d928baba52b`
- Sampling/config: temperature 0.6, top_p 0.95, max_completion_tokens 256, reasoning_effort none, persistent httpx transport
- Baseline prompt: `inventory-v1`, SHA-256 `73389babc2efe72bf28a8207a2b5e2c84d4e7cf2f11eeff9c11eb64c7012f9b8`
- Baseline Actions run: `35692991475`, artifact `10678874003` (`live-eval-report-groq-v1`)
- Variant prompt: `inventory-v2-strict`, SHA-256 `bdf294540c2a58248245d317aa1c64d851a3a38bcb001ef1634e6e4951e686da`
- Variant Actions run: `35693419399`, artifact `10679222715` (`live-eval-report-groq-v2-strict`)

Provider, model, provider config, corpus, fixture, and case set are identical between reports.

## Automated result

| Case | inventory-v1 | inventory-v2-strict | Notable evidence |
| --- | --- | --- | --- |
| find-01 | failed, 1 round | completed/pass, 2 rounds | v1 generated nonexistent `find_items`; Groq rejected it before backend execution. v2 used `search_items`. |
| move-01 | completed/pass, 7 rounds | completed/pass, 3 rounds | v1: 7 tool calls, 3 `move_item` attempts, 2 backend tool errors, 64 s retry delay. v2: 3 tool calls, one `move_item`, no tool errors, no retry. |
| create-01 | failed, 7 rounds | completed/pass, 4 rounds | v1 eventually emitted malformed `aliases` for `create_item`; Groq rejected schema. v2 created one item successfully. |
| ambiguity-01 | failed, 1 round | completed/pass, 2 rounds | v1 generated nonexistent `find_item`. v2 used `search_items` and returned both candidates without mutation. |
| history-01 | completed/pass, 3 rounds | completed/pass, 3 rounds | Same tool shape: `search_items` + `get_item_history`; both answers grounded in history. |

Summary:

- `inventory-v1`: 2/5 completed and automatically passed; 3 provider tool-use failures.
- `inventory-v2-strict`: 5/5 completed and automatically passed.
- The largest deterministic tool-loop reduction was `move-01`: 7 -> 3 rounds and 13,939 -> 4,909 prompt tokens.
- Wall-clock time is heavily distorted by Groq minute limits. Retry delay was 64 s for v1 `move-01`; v2 had zero retry delay on that case. Do not interpret raw wall time as model inference speed.

## Manual-review notes

- This is a single stochastic sample at temperature 0.6. It is evidence of better tool discipline in this run, not enough evidence to declare a general prompt winner.
- `ambiguity-01` under v2-strict safely listed both matching multimeters and their locations, but then said “if you mean the main one...” instead of asking an explicit clarification question. Human review should decide whether listing both is acceptable or whether the strict prompt should require an actual clarification turn.
- Provider-side invalid tool generations are failures even though they never reached the inventory backend. They must remain visible in evaluation rather than being converted into aliases or silently retried as different tools.
- Before changing the default prompt, repeat a small tool-discipline subset and collect human pairwise reviews.
