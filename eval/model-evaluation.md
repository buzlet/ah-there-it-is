# Provider/model benchmark and promotion evidence

The benchmark flow is report-only. It does not change the application's configured provider or model.

## 1. Define a campaign

Copy `eval/benchmark-campaign-v1.example.json` and pin all identity fields:

- provider, model and a human-readable config label;
- prompt version, file and SHA-256;
- live-eval corpus version/file and ordered case IDs;
- model-probe suite version/file and ordered case IDs;
- live-case repetition count;
- optional delay between provider requests;
- output directory and file prefix.

Campaign files must not contain API keys, authorization headers or other credentials.

## 2. Run baseline and candidate campaigns manually

The standalone runner uses the provider already selected in the normal application environment. Run each campaign explicitly; no test or CI path invokes a live provider.

```text
.venv/bin/python -m ah_there_it_is.benchmark_campaign eval/<baseline-campaign>.json
.venv/bin/python -m ah_there_it_is.benchmark_campaign eval/<candidate-campaign>.json
```

Results are durable JSON. Each completed attempt is atomically persisted, and rerunning an incomplete campaign resumes only when provider/config/prompt/corpus/probe/campaign identity is unchanged.

## 3. Compare evidence

```text
.venv/bin/python -m ah_there_it_is.benchmark_compare \
  eval/results/benchmark-v1/baseline.json \
  eval/results/benchmark-v1/candidate.json \
  --json-output eval/results/benchmark-v1/comparison.json \
  --markdown-output eval/results/benchmark-v1/comparison.md
```

Comparison keeps hard correctness, behavioral/repeatability, and operational observations separate. There is no overall score and no automatic winner. Token/cost values remain unavailable/null when the provider did not report them.

## 4. Generate promotion evidence

```text
.venv/bin/python -m ah_there_it_is.promotion_report \
  eval/results/benchmark-v1/baseline.json \
  eval/results/benchmark-v1/candidate.json \
  --comparison-evidence eval/results/benchmark-v1/comparison.json \
  --output-dir eval/results/promotion-v1
```

The hard gate fails closed when declared attempt evidence is incomplete or when candidate evidence contains provider/tool-contract, application-check, write-target-safety, mutation-correctness, quantity/removed/Undo, or unsupported-fact failures. Cost and latency are reported as operational observations only.

A passing report is evidence for a human promotion decision. It never edits runtime configuration, `.env`, provider settings, or model defaults.
