# Post-0050 engineering backlog

Status: reconciled after merged batch 0041–0050; still not implementation authority.

Batch 0041–0050 merged as PR #68 at `ab48fa819101416b6976b6b3b4989e231273e110`. Its exact CI head `d0731f7b8069b8c7e540faeaa40306ffcddaab07` passed 450 tests, 58/58 scenarios and 86/86 retrieval cases. The audit findings below were rechecked against that merged code.

## Priority A — recovery and portable-scale closure

### Bound physical/FK validation diagnostics

Confirmed after 0050: `validate_database()` still calls `fetchall()` for both `PRAGMA integrity_check` and `PRAGMA foreign_key_check`. Doctor semantic/FTS sampling is bounded, but the storage-level physical validation path can still retain an unbounded diagnostic result.

Post-0050 action:

- bound storage-level integrity/FK diagnostic retention without weakening pass/fail correctness;
- use exact FK violation counts where SQLite permits count/projection queries and bounded deterministic samples for reporting;
- preserve machine-readable exact health/failure semantics;
- add large-corruption structural coverage rather than timing thresholds.

This task must not weaken SQLite integrity, schema-head, or foreign-key correctness checks.

### Memory-bounded portable import

Confirmed after 0050: portable export is projection-based, streaming and snapshot-consistent, but import still starts with `Path.read_text()` → `json.loads()` → one complete Pydantic `PortableDocument`. Assignment 0045 bounded database write behavior but did not bound input-document retention.

Post-0050 action:

- measure the delivered importer before changing it;
- make large portable-v2 import bounded in retained Python state, especially `history.events`;
- preserve whole-document semantic validation, stable-ID/reference validation, hierarchy checks, duplicate rejection, timestamp semantics, frozen v1 compatibility and atomic publication;
- compact ID/reference indexes or a temporary staging SQLite database are acceptable;
- do not trade bounded memory for silently partial validation.

The objective is not necessarily O(1) memory; it is to avoid retaining full heavyweight event/item payload graphs merely because the file is large.

## Priority B — verification/process closure

### Coverage regression gate — resolved

The exact-head CI for 0041–0050 reported 6746 statements, 902 missed, 1662 branches and 310 partial branches, with coverage displayed as 84%. Earlier representative implementation heads also remained at 84% while the codebase grew.

The CI report now uses two-decimal display precision and a conservative `--fail-under=83.00` floor. Coverage tooling remains CI-only. This is a regression guard, not a target for reducing tests or coverage.

### Protocol v8 completion evidence

The committed batch review exists before PR creation and cannot truthfully contain its own final head SHA, authoritative CI result, merge SHA or final-main SHA without a self-reference. Protocol v8 now assigns those facts to the external completion report after merge.

Future batches should keep one pre-PR review and one compact post-merge completion report; no post-merge history rewrite is required.

### Active-context archival

Completed batch material must be moved from active `assignments/`, `batches/` and `reviews/` to `archive/` after acceptance. The audit branch archives completed material through 0050. Future accepted batches must likewise leave only currently issued material active.

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
