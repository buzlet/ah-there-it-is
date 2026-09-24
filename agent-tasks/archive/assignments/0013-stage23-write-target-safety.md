# Assignment 0013: Stage 23 write target safety

Protocol: `agent-tasks/common/v4.md`

Branch: `feat/stage23-write-target-safety`

## Objective

Make agent mutation authorization safe against omitted arguments, weak search matches, truncated result sets, and stale identity evidence without changing search ranking semantics.

## Required behavior

- Make `MoveItemInput.location_id` required but nullable. Omitted `location_id` must return invalid arguments with no mutation/event; explicit `null` keeps the current intentional take/remove behavior.
- Verify the exported tool schemas and both provider adapter contract paths preserve required-nullable semantics. If a supported provider cannot safely represent this schema, use an explicit separate take/remove tool rather than restoring an optional default.
- Stop treating a singleton result or score gap as write authorization. Search candidates remain readable/seen; ranking score, result count and `SearchInput.limit` never independently grant mutation permission.
- Add a backend write resolver whose strong evidence is checked against the complete relevant database set, not the returned candidate slice:
  - Item: resolve only when the normalized query identifies exactly one Item across canonical names and aliases considered together. Canonical↔alias and alias↔alias collisions across Items are ambiguous. Exact generic attribute values, tags, substring and FTS matches are read-only evidence.
  - Location/Category: resolve by exact full path, or by an exact leaf name only when that leaf is globally unique for the entity type. Duplicate leaves remain ambiguous.
  - An entity created in the current run may continue to be used under the existing frozen-capability rules.
- Preserve enough resolution evidence to re-check the same normalized identity/path immediately before mutation. **Acceptance invariant:** conflict detection must examine all matching rows with the same normalization rules used by the resolver, and the re-check must be atomic with the mutation (same write transaction or equivalent conditional-write protection). On conflict/staleness, no data changes and no successful mutation result.
- Apply the re-check to every agent mutation that relies on a resolved existing Item/Location/Category ID; do not trust an accumulated bare ID from an earlier search.
- Keep read search ranking/results unchanged except where tests expose a correctness bug unrelated to authorization.

## Adversarial coverage

At minimum cover:

- two exact Items hidden behind `limit=1`;
- canonical name of one Item colliding with alias of another;
- alias collisions across Items;
- unique exact generic attribute/tag and weak singleton FTS/substring remain read-only;
- duplicate Location/Category leaf names vs exact full paths;
- mutation attempted after identity/path changes between resolution and write;
- omitted vs explicit-null move target;
- provider tool schemas for required nullable.

## Constraints

No schema migration, whole-turn rollback/receipt redesign, idempotency transaction refactor, Item lifecycle/unknown semantics, historical Event snapshot work, Activity UI, prompt tuning, dependency/runtime/workflow upgrades, or unrelated refactoring.

## Focused verification

Run focused dispatcher/resolution/provider-schema/concurrency-or-atomicity coverage required by this assignment, then the canonical v4 verification set.
