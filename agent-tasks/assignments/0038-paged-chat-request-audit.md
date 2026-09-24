# Assignment 0038: paged chat-request audit

## Objective

Make the local chat-request recovery/audit surface scalable and remove per-row recovery-source lookups.

Preserve idempotency/recovery semantics and existing API compatibility.

## Service read projection

Add a typed bounded list/page projection for ChatRequestRecord that can expose:

- record fields needed by current response/UI;
- recovered-from request key when applicable.

Resolve recovered-from keys in bounded set-based SQL rather than one `session.get()` per displayed record.

Do not change recovery mutation logic.

## HTML page

Update `/chat-requests`:

- page/page_size query parameters;
- default page size 50;
- maximum 100;
- deterministic current ordering by updated_at desc then id desc;
- previous/next navigation;
- same recovery forms/warnings/status information.

No fixed 200-row ceiling.

## API compatibility

Keep existing:

`GET /api/chat-requests?limit=N`

and its list response shape for existing callers.

Keep current maximum API limit unless a correctness issue requires otherwise.

Internally avoid per-row recovered-from lookup there as well.

Single-record endpoint remains unchanged.

## Tests

Cover:

- HTML pagination and order;
- API list compatibility;
- recovery-source key display;
- page/list query count does not grow linearly with number of returned recovery-linked records;
- 1000+ request records;
- invalid page/page_size/limit;
- recovery operations still produce identical durable semantics.

## Constraints

No idempotency/recovery write behavior change, no cleanup/retention policy, no schema/index migration.

## Checkpoint

Run only the 0038 focused checks from the manifest, then commit the 0038 checkpoint.
