# Session handoff

## Authoritative repository state

- Repository: `buzlet/ah-there-it-is`
- Default branch: `main`
- Verified main commit before this handoff: `8be0f80410644ad8f6d6ec97805bd4b9f849ebbd`
- That commit is the merge completing **Stage 11 — storage portability**.
- Both main-branch GitHub Actions runs created for that merge completed successfully.
- There are no open pull requests.
- `feat/stage12-portable-import` is currently identical to `main`: zero commits ahead/behind at the handoff point.
- Repository search found no existing portable-import implementation or dry-run import command. Stage 12 has not started in code.
- Numerous older `feat/stage6-*` through `feat/stage11-*` branches remain as historical branches. Do not infer unfinished work from their existence; use `main` and current PR state as authority.

## Current stage

Stages 0–11 are complete. **Stage 12 is next.**

Stage 11 delivered:

- validated WAL-safe SQLite backup and restore;
- independent integrity, foreign-key, and exact Alembic-head validation;
- pre-restore safety backups and atomic replacement;
- versioned `inventory-portable-v1` JSON export;
- portable export of category/location trees, items, aliases, tags, attributes, current locations, stable IDs/timestamps, and domain history;
- deliberate exclusion of conversations, chat-request recovery/idempotency state, evaluation traces, experiment traces, and provider metadata from the portable JSON;
- canonical Just recipes: `storage-test`, `db-backup`, `db-validate`, `db-restore`, and `portable-export`.

Full SQLite backup remains the disaster-recovery format. Portable JSON is only the implementation-independent inventory/history representation.

## Stage 12 objective

Make `inventory-portable-v1` reconstructable without weakening the SQLite disaster-recovery path.

The plan in `AGENTS.md` is authoritative:

1. Add a strict `inventory-portable-v1` parser/validator with explicit format/version rejection and useful structural errors.
2. Import only into a **new empty database** or a new output path. Never destructively merge into or overwrite the active database.
3. Validate all stable-ID references before writing:
   - category/location parent links;
   - item category/location links;
   - event item/from/to-location links;
   - duplicate IDs;
   - duplicate sibling names;
   - hierarchy cycles.
4. Preserve stable IDs and timestamps where they carry audit meaning. Recompute derived normalized fields instead of trusting serialized implementation details.
5. Reconstruct aliases, tags, attributes, current locations, and history; verify FTS/search-derived state after import.
6. Add export -> import -> export semantic round-trip tests, ignoring only intentionally volatile metadata such as `exported_at`.
7. Keep portable import scoped to inventory/history. Conversations, chat-request idempotency/recovery records, evaluation/model/provider traces remain SQLite-backup-only.
8. Add a dry-run validation command before any import creates an output database.
9. Keep provider/model work and deferred product features out of Stage 12.

## Read these files first

In this order:

1. `HANDOFF.md` — this checkpoint.
2. `AGENTS.md` — architecture invariants, development rules, completed stages, and Stage 12 plan.
3. `README.md` — current user/developer behavior, pipelines, idempotency, provider separation, backup/restore/export usage.
4. `src/ah_there_it_is/storage.py` — Stage 11 backup/restore/export implementation and `inventory-portable-v1` document shape.
5. `src/ah_there_it_is/storage_cli.py` — storage CLI boundary to extend.
6. `tests/test_storage.py` — current storage invariants and fixtures; extend these before/with import implementation.
7. `src/ah_there_it_is/db/models.py` — persisted entities and constraints.
8. `src/ah_there_it_is/services/search.py` — derived deterministic/FTS behavior that must work after import.
9. `Justfile` — canonical commands. Do not invent duplicate ad-hoc command sequences.

## Recommended Stage 12 starting sequence

1. Start from current `main`. Reuse `feat/stage12-portable-import` only after verifying it is still identical to main; otherwise create a fresh focused feature branch.
2. Write validator/parser tests before import mutation code:
   - wrong/missing format;
   - malformed section types;
   - duplicate IDs;
   - dangling references;
   - self-parent/cycles;
   - duplicate sibling names;
   - invalid item/event references.
3. Implement a pure parse/validate representation that performs **no database writes**.
4. Add a dry-run CLI command around that validator.
5. Implement import into a brand-new migrated SQLite database only.
6. Verify stable IDs/timestamps plus derived normalized/FTS state.
7. Add semantic export -> import -> export comparison tests.
8. Run canonical checks and migration checks; update `AGENTS.md` at stage completion before merge.

## Important invariants not to regress

- The LLM never writes the database directly.
- Existing entities are mutated by stable IDs.
- Service/domain code owns validation and transaction boundaries.
- Material item mutations/history remain auditable.
- Agent turns are transactionally atomic.
- Chat request idempotency/recovery audit records are not part of portable inventory import/export.
- Full SQLite backup/restore and portable inventory import are different products with different guarantees.
- A portable import must never overwrite the active database or silently merge into a non-empty target.
- Do not trust serialized normalized/search fields; rebuild derived state through the current application schema/services/triggers.
- Normal application CI must not depend on external provider/model availability.

## Verification checkpoint

Before beginning Stage 12 implementation, re-check:

- `main` SHA and branch divergence;
- open pull requests;
- latest application/provider-contract CI status;
- that `feat/stage12-portable-import` has not acquired newer work since this handoff.

If repository state has moved, trust the newer repository state over this file and update this handoff accordingly.
