# Batch manifest: provider/model evaluation 0081–0083

Batch ID: post-0070-model-evaluation-2026-09-25

Protocol: agent-tasks/common/v8.md

Expected start main:

153435ef3272a134d85ff02bcc370b8121b0708a

Implementation branch:

feat/model-evaluation-0081-0083

Execution:
- host_profile: chatgpt-sandbox
- execution_channel: sandbox
- execution_user: sandbox
- workdir: /mnt/data/model-evaluation-0081-0083
- source_artifact: sandbox-bundle-153435ef3272a134d85ff02bcc370b8121b0708a

Batch review destination:

agent-tasks/reviews/0081-0083-model-evaluation-r1.md

Full local regression:

full_local_required: false

## Objective

Implement a provider/model benchmark and promotion-report subsystem by composing
the existing live-eval/model-probe/scenario evidence rather than changing
inventory behavior:

1. strict versioned benchmark campaign manifest;
2. repeated deterministic campaign orchestration and resumable durable results;
3. baseline/candidate aggregation without one opaque score;
4. explicit correctness hard gates;
5. reproducible report-only promotion evidence.

## Ordered tasks

1. 0081 — benchmark campaign schema and repeated runner
2. 0082 — benchmark aggregation and baseline/candidate comparison
3. 0083 — promotion hard-gate report and evaluation integration

Exact task specs:
- agent-tasks/batches/post-0070-model-evaluation/0081-benchmark-campaign-runner.md
- agent-tasks/batches/post-0070-model-evaluation/0082-benchmark-comparison.md
- agent-tasks/batches/post-0070-model-evaluation/0083-promotion-gate-report.md

Seed destinations:
- agent-tasks/assignments/0081-benchmark-campaign-runner.md
- agent-tasks/assignments/0082-benchmark-comparison.md
- agent-tasks/assignments/0083-promotion-gate-report.md

The one remote implementation seed commit and matching local sandbox seed must
contain this manifest at its active path and exact byte copies of all three task
specs at the assignment destinations above.

## Sandbox start procedure

1. Use the GitHub connector to locate the successful application-ci run for exact
   start-main 153435ef3272a134d85ff02bcc370b8121b0708a.
2. Download the exact artifact:
   `sandbox-bundle-153435ef3272a134d85ff02bcc370b8121b0708a`.
3. Extract it only into:
   `/mnt/data/model-evaluation-0081-0083`.
4. Verify `.sandbox/MANIFEST.txt` source_commit equals 153435ef3272a134d85ff02bcc370b8121b0708a.
5. Run `make sandbox-bootstrap` before edits.
6. Create local branch `feat/model-evaluation-0081-0083` from the synthetic
   sandbox baseline.
7. Use the GitHub connector to create the remote implementation branch from exact
   upstream 153435ef3272a134d85ff02bcc370b8121b0708a.
8. Fetch the immutable control files at the issued control SHA through the GitHub
   connector; do not use shell GitHub/network access.
9. Materialize active manifest/assignments locally and create the local seed.
10. Mirror the same active control material as the first remote seed commit on
    the implementation branch.

For each task checkpoint:

- commit locally after focused verification;
- mirror the checkpoint tree/changes as one remote commit using the GitHub connector;
- keep checkpoint order 0081 -> 0082 -> 0083;
- do not use shell `git fetch/push`, curl/wget or online pip/uv.

The remote GitHub branch/seed/checkpoints are the authoritative ancestry for the
eventual PR. Local synthetic commit SHAs are sandbox execution evidence only.

## Strict file ownership

This sibling lane may add/modify only evaluation-campaign/report implementation,
tests and evaluation examples/docs required by 0081–0083, plus its own active
assignment/batch review files.

It must not modify:

- inventory domain/services;
- database models or migrations;
- Web routes/templates/static assets;
- Telegram/media modules/tests owned by 0071–0080;
- runtime_cli.py;
- config.py;
- pyproject.toml;
- Makefile;
- AGENTS.md;
- HANDOFF.md;
- .github workflows;
- product design decisions.

No new dependencies.

## Sibling parallel batch

Batch 0071–0080 is intentionally issued from the same start-main SHA.

An origin/main advance caused **solely** by merge of the issued sibling
0071–0080 batch is explicitly authorized and is not a v8 stop condition.

If that happens:

- do not rebase/merge sibling commits into local or remote task history mid-batch;
- continue from issued start-main;
- before final merge require the PR to be conflict-free against current main;
- authoritative exact-head PR CI must validate against current main;
- stop if sibling changed a file owned by this batch or if main advanced for any
  unrelated reason.

## Provider/network policy

- normal sandbox tests use fakes/fixtures only;
- do not call live Gemini/Groq/OpenAI/other providers;
- do not require provider credentials;
- do not add a live-provider CI requirement;
- no shell network access.

## Final focused integration

After 0083 run exactly:

    .venv/bin/python -m pytest -q       tests/test_benchmark_campaign.py       tests/test_benchmark_comparison.py       tests/test_promotion_report.py       tests/test_live_eval.py       tests/test_live_compare.py       tests/test_model_probe.py       tests/test_evaluation.py       tests/test_evaluation_export.py       tests/test_scenario_eval.py       tests/test_eval_checks.py
    make provider-contract
    make compile
    git diff --check

Because `full_local_required: false`, do not run `make check` or the universal
full-local sequence in sandbox. Exact-head application CI owns repository-wide
regression.

## Stop conditions

Stop rather than expand scope if implementation would require:

- inventory/Telegram/media/runtime changes;
- migrations;
- a new dependency;
- live provider access for tests;
- automatic provider/model promotion;
- writing secrets into campaign/results;
- a single opaque quality score hiding hard correctness failures;
- changing application model configuration;
- changing CI or Makefile;
- multilingual expansion.

## Final lifecycle

After 0083:
- cumulative local and remote seed..HEAD self-review;
- one pre-PR batch review;
- final focused integration only;
- one PR from the remote implementation branch;
- authoritative exact-head CI;
- narrow correction loop only if required;
- merge commit after green exact head;
- verify remote seed ancestry;
- compact completion report.
