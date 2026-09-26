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
- Item photo associations stored as provider + opaque external media references (never image bytes);
- single-user/private-text Telegram long polling through the shared chat/idempotency service;
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

For the U24 target host, see [the deployment runbook](deploy/README.md).

### Telegram bot and Item media

Run the Telegram adapter only as an explicit process after the database has been
upgraded to the packaged migration head:

```bash
python -m ah_there_it_is.storage_cli upgrade
ah-there-it-is telegram-bot
```

Set `AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN` and
`AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID` for that command. The adapter accepts
only nonblank text from that user in a private chat. It uses `getUpdates` long
polling, deterministic `telegram:<update_id>` request keys and a durable offset.
Inventory effects are exactly-once under request-key replay; a reply may be
resent after an uncertain send/checkpoint boundary. Web startup never starts the
Telegram process.

Item photos are associations, not uploads. The HTTP API is:

- `GET /api/items/{item_id}/media` — ordered refs;
- `POST /api/items/{item_id}/media` — `{provider, media_reference, caption?, position?}`;
- `PATCH /api/items/{item_id}/media/{media_id}` — caption/order metadata;
- `DELETE /api/items/{item_id}/media/{media_id}` — detach only.

The same endpoints are available under the compatibility `/photos` path. Image
bytes, external media deletion, Telegram webhooks/groups/photo ingestion,
vision/image recognition, and generic User/Channel/Role models are outside this
core MVP.

Normal implementation uses focused task checkpoints and one final CI regression; it does not run the entire suite after every batch task.

## Current documentation

- `AGENTS.md` — architecture/process rules;
- `HANDOFF.md` — current handoff;
- `PROJECT-MODULE-MAP.md` — module map;
- `agent-tasks/common/v8.md` — active implementation protocol;
- `agent-tasks/designs/future-decision-gates.md` — unresolved decisions.

Historical process material is under `agent-tasks/archive/` and is not normal agent context.
