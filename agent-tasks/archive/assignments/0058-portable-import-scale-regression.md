# Assignment 0058: portable import scale/failure regression

## Objective

Establish a structural target-scale regression proving that the new portable import path is complete, memory-bounded in retained Python payload state, compatibility-safe and failure-atomic.

## Required fixture

Build a deterministic portable-v2 source representing at least:

- 100–250 nested Location nodes;
- representative Category hierarchy;
- >=1000 Items;
- aliases, tags, structured attributes and mixed Item states/location truth;
- >=10,000 Events with nontrivial payload/original-text content;
- intentionally non-canonical array ordering where legal.

The fixture may be generated directly or by extending the existing target-scale generator, but must remain deterministic and test-only.

## Required proofs

### Bounded input/read structure

Prove structurally, not by wall-clock timing, that production import/dry-run:

- never call `Path.read_text()`, whole-document `json.load/json.loads`, or `load_portable_inventory()`;
- perform bounded-size source reads;
- retain only bounded current parser/batch payloads plus compact validation indexes;
- do not hydrate all Items or Events into an ORM identity map;
- use explicitly bounded insert batches.

A test-only instrumentation hook/tracking stream is acceptable. Avoid machine-dependent RSS/timing thresholds.

### Semantic roundtrip

Run:

`streaming export -> bounded dry-run -> bounded import -> streaming re-export`

and compare portable semantics while ignoring only already-defined volatile fields such as `exported_at`.

Preserve stable category/location/item/event IDs, hierarchy, state/location truth, aliases/tags/attributes, history payload/text/references and exclusions.

### Failure atomicity

Inject a failure near the end of a large source and prove:

- no destination publication;
- no leaked working/publish/parser temporary files;
- source and active DB unchanged.

Retain existing target-race tests from 0046.

### Compatibility

The frozen hand-authored v1 fixture must still validate/import/search/re-export through the current compatibility contract.

## Constraints

No timing benchmark, new dependency, format/schema change, retention policy or product semantics.

## Focused verification

Use the manifest-declared 0058 check only.
