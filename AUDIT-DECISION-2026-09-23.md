# Decision after audit reply

**Project:** `buzlet/ah-there-it-is`  
**Source audit:** `AUDIT-2026-09-23.md`  
**Our response:** `AUDIT-RESPONSE-2026-09-23.md`  
**Auditor reply:** `AUDIT-REPLY-2026-09-23.md`  
**Decision date:** 2026-09-23

## Summary

We accept the auditor's revised direction.

The reply improves the original remediation plan in three important ways:

1. write resolution must be checked independently of search result truncation;
2. turn rollback needs a simple deterministic state machine rather than a model-dependent notion of a later “recovery”;
3. the previous broad Write Safety stage should be split into smaller implementation stages.

The existing seeded Assignment 0012 should therefore be archived as superseded-before-execution, preserving its immutable seed history, before the next implementation assignment is issued.

## Accepted decisions

### 1. Supersede Assignment 0012 before implementation

Accepted.

`feat/stage23-browser-activity` currently contains only the Stage 23 seed and no implementation. We will preserve that history rather than abandon the branch.

Planned process:

- add `agent-tasks/reviews/0012-r0.md` on the existing seeded branch;
- update its status documents to state that the Activity plan was superseded before execution because the external audit changed priority;
- open a docs-only PR from that branch;
- merge with a merge commit, not squash/rebase;
- only after that merge create Assignment 0013 from the new `main`.

This is an exceptional archival/process PR, not an implementation lifecycle.

### 2. Write target safety becomes the next implementation stage

Accepted.

The next implementation assignment should be narrowly scoped to R1 + R2 and adversarial resolution tests.

It should not also attempt receipts, turn transaction redesign, idempotency crash handling, location lifecycle semantics, or Activity UI.

#### R1

`move_item.location_id` becomes required-but-nullable.

Missing field:
- validation failure;
- no mutation.

Explicit `null`:
- preserves the existing explicit “take/remove from storage” meaning for now.

Provider-schema behavior must be tested through the generic contract layer. If a supported provider cannot represent a required nullable field safely, introduce a separate explicit `take_item(item_id)` tool rather than restoring an optional default.

#### R2

Search ranking must not authorize writes.

The write resolver must evaluate database evidence independently of:
- `SearchInput.limit`;
- result count returned to the model;
- ranking score;
- score gap;
- substring/FTS ordering.

The initial safe rule should be conservative.

For Item write resolution:
- unique exact canonical name may resolve;
- unique exact alias may resolve only after checking collisions against canonical names and aliases of other Items;
- intentional duplicate canonical names remain ambiguous;
- tag, generic attribute value, substring and FTS evidence are read-only;
- a just-created Item can remain usable in later rounds under frozen-capability rules.

For Location/Category:
- exact full path may resolve;
- globally unique exact leaf name may resolve;
- duplicate leaf names remain ambiguous.

A result set truncated to one row must never imply uniqueness.

The resolver should revalidate the strong evidence immediately before mutation. We do not plan to add general optimistic-version tokens in this stage.

### 3. Atomic turn outcome + mutation receipts becomes a separate stage

Accepted with one clarification.

The auditor's state-machine formulation is preferable:

- before the first successful data-changing operation, read-tool errors may be returned to the model for correction;
- a mutation-tool error immediately fails and rolls back the turn;
- after the first successful data-changing operation, any subsequent tool error immediately fails and rolls back the turn;
- a later model call cannot “repair” that turn;
- empty final response after a change fails and rolls back;
- no-op operations must report `changed=false` and must not create false confirmation.

This stage should also introduce backend mutation receipts and authoritative API output such as:
- `changes_applied`;
- committed receipts.

Receipts belong in:
- `AgentRunResult`;
- a dedicated persisted field on `AgentRunLog`.

Domain `Event` remains domain history and should not become a second receipt store.

Important transaction distinction:
- a receipt produced after service flush is provisional;
- it becomes committed only if the enclosing turn commit succeeds;
- failed traces may retain attempted diagnostic data, but must mark it rolled back and must not expose it as committed state.

This stage also needs an explicit policy for the user message of a failed turn. A previously committed user message must not later look like a successfully completed prior instruction with no outcome. Either failed turns are excluded from future model context or represented explicitly as failed attempts.

### 4. Idempotency crash consistency remains its own stage

Accepted.

This follows the runner/receipt work rather than being merged into it.

Target:
- reservation may commit before the model call;
- business mutations;
- completed run;
- committed receipts;
- `ChatRequestRecord.status=completed`;
- `agent_run_id`;

must become one atomic final keyed transaction.

The fault-injection suite must distinguish:
- failure before final commit;
- successful commit followed by failure before HTTP response;
- uncertain/exceptional commit outcome.

If commit outcome is uncertain, the request must not immediately be marked failed. Durable state should be re-read through a fresh transaction/connection before deciding whether execution committed.

### 5. Historical Activity remains deferred

Accepted.

The Activity UI itself is not unsafe, but it should follow trustworthy history semantics.

For new Item Events we accept the auditor's proposed direction:
- retain stable Location ID;
- snapshot path components as structured pairs such as `{location_id, name}`;
- store snapshots in versioned Event payload data rather than a new relational history subsystem;
- collect from/to snapshots at event time.

Old Events without snapshots must not be backfilled with current paths as if they were historical truth. The UI should explicitly identify any rendered current path as current.

Portable-v1 already preserves Event payload and therefore should be tested for round-trip preservation of the new snapshot fields rather than changed merely because snapshots are introduced.

Category historical naming needs the same review if future Activity presentation claims historical category labels.

## Refined implementation order

### Assignment 0013 / Stage 23 — Write target safety

- R1 required nullable move target;
- R2 independent write resolver;
- remove score-gap/singleton write authorization;
- provider schema contract for required nullable;
- adversarial `limit=1`, duplicate canonical/alias collisions, weak exact attribute, substring and FTS cases.

### Stage 24 — Atomic agent turn + committed receipts

- deterministic rollback state machine;
- mutation receipts;
- authoritative `changes_applied`;
- persisted receipts in run log;
- no-op semantics;
- failed-turn conversation-context semantics.

### Stage 25 — Idempotency crash consistency

- atomic keyed final transaction;
- fault injection around commit/response;
- uncertain commit-state reconciliation;
- concurrent/replay tests;
- separately measure SQLite write-lock behavior across slow model rounds before changing architecture.

### Stage 26 — Location truth / manual fallback

Design before implementation:
- unknown vs in-use/taken vs disposed;
- consistency with existing `ItemState`;
- conservative migration of old null locations;
- unknown browser filter;
- suggestions only after lifecycle semantics are clear;
- identical-instance UX only if concrete scenarios justify it.

### Stage 27 — Historical evidence + Activity

- structured path snapshots for new Events;
- honest rendering of old Events;
- portable round-trip coverage;
- then the deferred Activity timeline.

## Additional adversarial tests accepted

Add these to the appropriate stages:

- two exact Item/alias matches with search `limit=1`;
- alias of one Item colliding with canonical name of another;
- exact generic attribute value remains read-only evidence;
- weak singleton FTS result remains read-only;
- dirty ORM state followed by tool error cannot be accidentally flushed by another tool;
- successful mutation followed by read-tool error rolls back;
- later corrected call does not resurrect a failed post-mutation turn;
- no-op update/move produces `changed=false`, no new Event, no false “changed” receipt;
- failure before commit;
- successful commit then response failure;
- uncertain commit result;
- old Event without snapshot after tree rename/reparent;
- new Event snapshot survives portable export/import;
- concurrent manual change between model search and write is revalidated at mutation time;
- measure, rather than assume, SQLite lock behavior during a long model round after first write.

## Deliberate non-goals

These audit findings still do not justify:
- vector search or embeddings;
- async ORM;
- event sourcing;
- generic repositories;
- SPA;
- microservices;
- cloud sync;
- provider-specific prompt expansion.

## Immediate next process action

Do not start the seeded Activity implementation.

Archive Assignment 0012 as superseded-before-execution through its existing branch, then seed Assignment 0013 from the resulting `main`.

