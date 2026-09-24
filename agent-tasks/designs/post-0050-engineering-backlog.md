# Post-0050 engineering backlog

Status: orchestration audit backlog; not implementation authority.

This file records engineering follow-ups identified by the 2026-09-25 orchestration audit. The active storage/recovery batch 0041–0050 must finish unchanged first. After that batch is accepted, this backlog is reconciled against its actual implementation and only then converted into immutable issued task specs.

## Priority A — recovery and portable-scale closure

### Bound physical/FK validation diagnostics

Current recovery validation can retain the complete result of `PRAGMA foreign_key_check` in Python. Assignment 0050 bounds doctor samples for several high-cardinality semantic/FTS diagnostics, but its immutable scope does not explicitly require the physical/FK validation path to be bounded.

Post-0050 action:

- inspect the delivered 0050 implementation first;
- if `validate_database()` and doctor/recovery paths can still materialize all FK violations, replace that retention with exact counts plus bounded deterministic samples;
- preserve machine-readable exact health/failure semantics;
- add large-corruption structural coverage rather than timing thresholds.

This task must not weaken SQLite integrity, schema-head, or foreign-key correctness checks.

### Memory-bounded portable import

Portable export is being made projection-based, streaming, snapshot-consistent and scale-tested in 0041–0044, while import still begins from a complete decoded JSON/Pydantic document and 0045 only batches database writes.

Post-0050 action:

- measure the delivered importer before changing it;
- make large portable-v2 import bounded in retained Python state, especially `history.events`;
- preserve whole-document semantic validation, stable-ID/reference validation, hierarchy checks, duplicate rejection, timestamp semantics, frozen v1 compatibility and atomic publication;
- compact ID/reference indexes or a temporary staging SQLite database are acceptable;
- do not trade bounded memory for silently partial validation.

The objective is not necessarily O(1) memory; it is to avoid retaining full heavyweight event/item payload graphs merely because the file is large.

## Priority B — verification/process closure

### Coverage regression gate

Coverage was deliberately report-only until several representative implementation PRs established a stable baseline. Representative exact-head CI runs from 0024 through 0040 remained at 84% rounded branch coverage while the codebase grew materially.

After 0041–0050:

1. read the exact coverage result on the final storage batch head;
2. choose a non-rounded regression floor or equivalent baseline policy from measured data;
3. make the gate fail only on meaningful regression, not on display rounding;
4. keep coverage tooling CI-only.

Do not guess a threshold before the storage batch lands.

### Protocol v8 completion evidence

The committed batch review exists before PR creation and cannot truthfully contain its own final head SHA, authoritative CI result, merge SHA or final-main SHA without a self-reference. Protocol v8 now assigns those facts to the external completion report after merge.

Future batches should keep one pre-PR review and one compact post-merge completion report; no post-merge history rewrite is required.

### Active-context archival

Completed batch material must be moved from active `assignments/`, `batches/` and `reviews/` to `archive/` after acceptance. The audit branch archives 0035–0040. After 0041–0050 is accepted, archive that completed batch as part of the final reconciliation and leave only currently issued material active.

### Executor-boundary enforcement

The protocol currently requires the implementation agent to assert execution user/workdir repeatedly. Prefer moving enforceable user/workdir restrictions into the launcher/executor boundary where practical, leaving protocol checks as defense in depth rather than the primary sandbox boundary. This is process tooling only and must not relax the unique-checkout rule.

## Priority C — lower-risk correctness hardening

### Empty Conversation on failed first turn

`AgentRunner` creates a new Conversation through a service method that commits immediately, including when keyed execution later owns the final success transaction. A first-turn failure can therefore leave an empty Conversation row even though failed user/assistant messages are intentionally excluded.

Investigate changing new-conversation creation to participate in the owning turn/keyed transaction while preserving existing unkeyed behavior and crash-safe idempotency semantics.

### Manual/browser concurrent-write consistency

Agent writes acquire a SQLite write lock and revalidate identity evidence immediately before mutation. Manual browser mutations share domain validation but not that agent-specific identity revalidation boundary.

No change is required for the current single-user loopback product. Before introducing meaningful concurrent/multi-user access, add explicit stale-write/concurrency semantics for manual mutations rather than relying on last-writer timing.

### Storage publication platform assumptions

Assignments 0046–0049 target the local POSIX filesystem model used by the current U24 implementation path. Do not claim equivalent Windows/network-filesystem crash guarantees from those tests.

If Windows becomes an actual application storage runtime target, add a platform-specific publication/recovery contract and fault/race coverage instead of generalizing POSIX rename/link/fsync assumptions.

## Python verification policy

Python 3.12 is intentionally the only required CI/test compatibility target.

Do not add Python 3.13, 3.14, 3.15, 3.16 or other later-version test matrices, smoke lanes, or compatibility work merely because those interpreters exist. A newer Python verification target requires a separate explicit project decision.

This policy does not require artificially setting `requires-python <3.13`; package metadata may remain permissive where the code happens to work.
