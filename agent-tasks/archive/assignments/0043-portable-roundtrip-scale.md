# Assignment 0043: target-scale portable roundtrip regression

## Objective

Add a deterministic target-scale regression proving that the new projection/streaming export plus existing import preserve portable inventory/history semantics end to end.

## Fixture

Use efficient test setup to build approximately target product scale:
- 100–250 nested locations/categories in a nontrivial tree;
- at least 1000 items;
- aliases, tags, attributes and mixed nonterminal/terminal states;
- representative event history.

Do not use provider/model calls.

## Assertions

Export source DB -> import into a brand-new DB -> export imported DB again.

Compare canonical portable payload semantics while intentionally ignoring only fields that are expected to differ by export invocation (for example `exported_at`).

Prove:
- category/location/item stable IDs preserved;
- hierarchy preserved;
- aliases/tags/attributes preserved;
- state/location_status/location IDs preserved;
- events and historical evidence preserved;
- deterministic ordering;
- provider/conversation/evaluation/experiment tables remain excluded;
- imported database passes physical validation, doctor and search consistency.

Use structural assertions, not timing thresholds.

## Constraints

Do not change portable semantics merely to satisfy the test. If a real incompatibility is exposed, fix only within existing portable-v2 contract.

## Checkpoint

Run:
```text
.venv/bin/python -m pytest -q tests/test_storage.py -k "portable and roundtrip"
just compile
git diff --check
```
Then commit checkpoint 0043.
