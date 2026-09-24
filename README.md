# Ah, There It Is!

Local-first inventory memory for finding and maintaining physical things through deterministic browser tools and a provider-neutral LLM agent.

## Current product

The application is a FastAPI + SQLite inventory with:

- nested Locations and Categories;
- Items with stable IDs, names, aliases, tags, structured attributes, quantity and condition/state;
- explicit location truth: `known`, `unknown`, `in_use`, `not_applicable`;
- terminal Item states including `sold` and `discarded`;
- immutable Item Event history with historical Location/Category path evidence;
- deterministic exact/normalized/FTS retrieval;
- browser catalog/search/admin and Activity timeline;
- provider-neutral bounded agent tool loop;
- transactional agent turns, mutation receipts and request idempotency;
- local database doctor, FTS repair, backup/restore and restore rehearsal;
- portable inventory v2 export/import with frozen v1 import compatibility;
- deterministic offline scenario and retrieval evaluation.

The LLM never writes the database directly. Domain services own validation, identity, invariants, transactions and history.

## Local runtime

Python: `>=3.12`.

Install for development:

```bash
python -m venv .venv
python -m pip install -e '.[test]'
```

Create or upgrade the database explicitly:

```bash
python -m ah_there_it_is.storage_cli upgrade
```

Run locally:

```bash
ah-there-it-is serve
```

The installed server binds to loopback by default. Non-loopback serving requires explicit `--allow-nonlocal` and is still unauthenticated.

Default data home is stable per-user. On Windows it uses `LOCALAPPDATA\AhThereItIs`; on Unix it follows XDG conventions. `AH_THERE_IT_IS_DATABASE_URL` overrides the default database URL when nonblank.

## Canonical development commands

`Justfile` is the authoritative repeated-command surface:

```bash
just check
just migration-check
just corpus-check
just scenario-check
just scenario-eval
just retrieval-eval
just provider-contract
```

Other operational recipes include:

```bash
just serve
just db-backup <destination>
just db-validate <database>
just db-restore <candidate>
just db-restore-rehearsal <candidate>
just portable-export <destination>
just portable-import-dry-run <source> <destination>
just portable-import <source> <destination>
just bootstrap-preflight <source>
just bootstrap-apply <source>
```

Normal application CI runs on pull requests and remains provider/model independent. Coverage is collected only in CI and is currently report-only.

## Inventory semantics

### Location truth

An Item has one explicit location status:

- `known`: a current Location exists;
- `unknown`: the Item is tracked but its whereabouts are unknown;
- `in_use`: intentionally taken from storage / currently outside a stored Location;
- `not_applicable`: terminal/non-possessed Item such as sold or discarded.

A blank Location field is never an implicit state transition. Move, take, mark-unknown, sold/discarded and reactivation are explicit operations.

Terminal Items remain searchable so the system can answer what happened to an object. The blank browser catalog defaults to active Items and offers lifecycle filters.

### Search

Retrieval uses bounded deterministic exact/normalized/tag/attribute/FTS candidates and stable ranking. Write authorization is stricter than read search: weak search ranking never authorizes mutations.

The committed RU/UK/EN retrieval corpus is the measurement baseline. Typo correction, transliteration, morphology and embeddings are not current product requirements.

## Agent/application separation

Application correctness is evaluated with deterministic scenario mocks. Provider/model behavior is a separate pipeline.

Normal development must not depend on a particular model. Provider adapters implement the common `LLMClient` contract; live provider probes are manual.

Agent turns are transactionally atomic. Failed mutation turns roll back. Successful mutations expose backend receipts independent of assistant wording. Retry-safe chat requests use stable idempotency keys.

## Storage and recovery

- SQLite backup/restore is the full-fidelity disaster-recovery mechanism.
- Restore rehearsal validates a candidate against an isolated fake active database and never restores over the real active database.
- Portable export/import is a separate inventory portability contract.
- Current export format is `inventory-portable-v2`; frozen v1 remains importable.
- Bootstrap import is a separate onboarding format and generates current IDs/history.

## Implementation process

Current implementation protocol: `agent-tasks/common/v7.md`.

Current process/architecture rules: `AGENTS.md`.

Current handoff: `HANDOFF.md`.

Historical assignments, reviews, batches, protocols and long status snapshots live under `agent-tasks/archive/` and are **not part of normal agent reading**. Consult the archive only when investigating a historical decision or regression.

## Current scope boundary

The next unresolved product-semantic gate is quantity / identical physical instances. No implementation agent should invent partial-quantity, split/merge or per-instance semantics before that gate is explicitly decided.

Other deferred gates are summarized in `agent-tasks/designs/future-decision-gates.md`.
