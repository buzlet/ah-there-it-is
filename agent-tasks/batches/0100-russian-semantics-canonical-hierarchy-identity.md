# Batch: 0100-russian-semantics-canonical-hierarchy-identity

Full local required: `false`

## Objective

Implement the Russian inventory-semantics cluster from issues #97, #98 and #99
as one coherent write/read boundary so canonical naming, relational location
hierarchy and entity identity do not contradict each other.

This batch exists because the three issues share the same interpretation and
mutation boundary. Do not solve them as unrelated post-processing hacks.

## Production evidence

Observed production failures include:

- `тумбочка в ванне` persisted as a flat root location instead of
  `ванна -> тумбочка`;
- inflected names can reach persistence/display rather than a stable dictionary
  form;
- a generic lexical head such as `бумага` must not silently reuse a more
  specific existing item such as `туалетная бумага`.

These are measured Russian-language failures and therefore satisfy the
`AGENTS.md` gate for adding narrowly justified Russian morphology/normalization
work.

## Product decisions

1. Russian remains the only supported natural language.
2. Canonicalization and identity resolution are different operations.
3. Search similarity never authorizes a mutation.
4. Relational syntax belongs in structure, not in canonical entity names.
5. Existing stable IDs must be reused only with strong identity evidence.
6. Ambiguous writes fail closed to clarification/distinct-entity behavior rather
   than silently mutating an uncertain target.
7. The LLM remains provider-neutral and never writes SQLite directly.
8. Do not make correctness depend on one concrete model name/provider.
9. Physical-containment plausibility is enabled by default, but must be exposed
   as an explicit product/deployment policy with at least a permissive mode for
   users who intentionally want abstract trees. Do not implement multi-user
   profiles in this batch.

## Work 1 — canonical Russian names

Add one explicit normalization boundary before entity create/match.

Required behavior:

- normalize inflected Russian item/location phrases to ordinary dictionary
  display forms where meaning is clear;
- examples:
  - `зубную щётку` -> `зубная щётка`;
  - `туалетной бумаги` -> `туалетная бумага`;
  - `в ванной` -> `ванна`;
  - `в тумбочке` -> `тумбочка`;
  - `на верхней полке` -> `верхняя полка`;
- trim/collapse whitespace and normalize cosmetic punctuation/quotes/dashes where
  safe;
- ordinary Russian names default to lowercase;
- preserve meaningful technical/brand casing such as `USB-кабель`,
  `SSD Samsung`;
- keep canonical display form separate from a comparison-normalized key;
- original/raw forms may remain as trace/search evidence but must not pollute the
  canonical display name.

Do not implement naive suffix stripping. If a morphology dependency is added,
keep it narrowly scoped, deterministic and justified by the observed failures;
avoid large NLP stacks when a smaller architecture is sufficient.

## Work 2 — relational location hierarchy

Interpret relational location phrases before location create/match.

Required behavior:

- `X в Y` -> child X under parent Y;
- `X внутри Y` -> child X under parent Y;
- `X на Y` -> hierarchy only where the physical/semantic relation is
  appropriate;
- nested chains such as `в коробке в шкафу в комнате` create/reuse the
  corresponding ordered hierarchy;
- existing parent locations are reused by strong canonical identity;
- no root location should be persisted with a canonical name containing a
  relationship phrase that should have become structure;
- genuine ambiguity requests clarification rather than persisting a misleading
  hierarchy.

Acceptance example:

```
ванна
└── тумбочка
```

for `в тумбочке в ванной`.

## Work 3 — containment plausibility policy

Prevent obviously nonsensical physical containment in the normal policy.

At minimum cover classes such as:

- room inside a drawer/cabinet;
- bedside cabinet inside a desk drawer;
- an obviously larger enclosing place inside a materially smaller child
  container.

Requirements:

- do not pretend uncertain world knowledge is a hard fact;
- use a conservative, inspectable policy boundary;
- when normal physical mode cannot establish a plausible relation, clarification
  is preferable to silently writing an absurd hierarchy;
- expose an explicit configuration setting using the existing settings
  architecture, conceptually:
  `AH_THERE_IT_IS_LOCATION_CONTAINMENT_POLICY=physical|permissive`;
- default to `physical`;
- `permissive` allows intentionally abstract/logical trees while still
  preserving structural integrity and cycle prevention;
- this is a global policy for the current single-user product; #101 owns future
  per-user layering.

Do not create a universal ontology or large hand-maintained taxonomy solely for
this task. Prefer the smallest defensible policy boundary supported by tests and
provider-neutral interpretation evidence.

## Work 4 — preserve entity specificity

Separate canonical equivalence from semantic identity.

Required behavior:

- exact canonical matches are strongest;
- true inflectional variants may resolve to the same entity;
- bare generic noun vs adjective+noun is not automatically identity;
- `бумага` must not mutate/reuse existing `туалетная бумага` merely because
  the lexical head overlaps;
- weak search/fuzzy/head-noun similarity may aid retrieval but cannot authorize
  a write;
- mutation of an existing entity must retain strong identity evidence and
  atomic revalidation;
- when identity is insufficient, clarify or create a distinct entity according
  to the command semantics;
- identity evidence remains inspectable in safe traces.

## Work 5 — provider-neutral interpretation and mocks

Keep product development independent from quirks of one live model.

- preserve the generic provider/tool contract;
- deterministic tests must use scripted/mock model behavior for all acceptance
  scenarios;
- any live-model probe is optional evidence, not the correctness oracle;
- do not encode provider/model names into domain semantics;
- do not add prompt-only behavior without a backend validation boundary when a
  wrong model answer could authorize a mutation.

## Required regressions

Add deterministic tests covering at minimum:

1. `зубную щётку в тумбочке в ванной` canonicalizes and creates/reuses
   `ванна -> тумбочка`;
2. an existing `ванна` is reused rather than duplicated;
3. nested three-level location chain;
4. ordinary lowercase/case/spacing/punctuation normalization;
5. meaningful technical casing preserved;
6. `туалетной бумаги` equals canonical `туалетная бумага`;
7. existing `туалетная бумага` followed by a mutation referring only to
   `бумага` does not mutate/reuse it without stronger evidence;
8. search may return a weakly related entity without that result becoming
   mutation authority;
9. normal physical policy blocks/clarifies an obviously implausible containment;
10. permissive policy accepts the same structurally valid abstract hierarchy;
11. cycles/self-parenting remain forbidden regardless of policy;
12. traces expose safe identity/normalization evidence without secrets.

Use existing transactional/idempotency tests as regression guardrails.

## Verification

Run focused tests for the changed interpretation, domain/service, search and
configuration boundaries.

Then:

```bash
make compile
git diff --check
```

Exact-head application CI is the repository-wide regression authority.

If dependency metadata changes, verify lock/build/install behavior required by
the repository and clearly report the added dependency rationale.

## Independent review emphasis

The reviewer must independently attack:

- canonicalization accidentally collapsing semantically distinct entities;
- generic-head matching authorizing writes;
- relationship phrases still leaking into persisted canonical location names;
- hierarchy order reversal in nested Russian phrases;
- duplicate parent creation;
- morphology rules that corrupt technical/brand identifiers;
- containment policy being cosmetic/prompt-only rather than protecting writes;
- physical mode overclaiming uncertain world knowledge;
- permissive mode bypassing structural invariants such as cycle prevention;
- configuration default/validation inconsistencies;
- transaction/idempotency regressions;
- model-specific behavior that deterministic mocks do not cover.

The reviewer is also the correction agent. Reproduce findings where practical,
append narrow regression tests and fixes to the same branch, never amend/rebase/
force-push, run focused verification and exact-head CI, then finish with
`REVIEW COMPLETE — CLEAN` or `REVIEW COMPLETE — CORRECTED`.

## Non-goals

- multilingual support;
- transliteration;
- embeddings/vector search;
- broad fuzzy matching;
- first-class multi-user/profile implementation;
- Telegram presentation/navigation work from #100;
- broad configuration architecture refactor from #101;
- universal physical-world ontology.

## Handoff

Implementation stops at `READY FOR REVIEW`.

Report the exact head, focused checks, dependency changes if any, PR/CI state and
remaining direct follow-ups.
