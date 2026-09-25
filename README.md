# Ah, There It Is!

Local-first inventory memory with deterministic browser tools and a provider-neutral LLM agent.

## Current capabilities

- nested Locations and Categories;
- Items with stable IDs, aliases, tags, attributes and exact / approximate / unknown quantity;
- known / unknown / in-use / not-applicable location truth;
- generic removed / restore lifecycle with explicit reasons;
- immutable Item Event history;
- deterministic exact/normalized/FTS retrieval;
- browser catalog/search/admin and Activity;
- provider-neutral bounded agent tools;
- atomic turns, mutation receipts and request idempotency;
- doctor/FTS repair;
- backup/restore/rehearsal;
- portable-v3 with frozen v1/v2 import support;
- immediate one-level compensating Undo for the preceding committed chat mutation;
- deterministic scenario/retrieval/provider evaluation.

The LLM never writes the database directly.

## Development

Python >=3.12.

```bash
python -m venv .venv
python -m pip install -e '.[test]'
python -m ah_there_it_is.storage_cli upgrade
ah-there-it-is serve
```

`Makefile` is the canonical repeated-command surface.

Normal implementation uses focused task checkpoints and one final CI regression; it does not run the entire suite after every batch task.

## Current documentation

- `AGENTS.md` — architecture/process rules;
- `HANDOFF.md` — current handoff;
- `PROJECT-MODULE-MAP.md` — module map;
- `agent-tasks/common/v8.md` — active implementation protocol;
- `agent-tasks/designs/future-decision-gates.md` — unresolved decisions.

Historical process material is under `agent-tasks/archive/` and is not normal agent context.
