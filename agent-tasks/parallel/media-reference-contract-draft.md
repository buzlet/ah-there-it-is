# Item media-reference contract

Status: **accepted core-MVP design** on 2026-09-25. Stored on the temporary planning branch until 0061-0070 merges.

Authoritative umbrella decision:
`agent-tasks/parallel/core-media-telegram-decision.md`

## Goal

Associate zero, one or many externally stored photos with an Item without storing image bytes or image-model behavior in the inventory core.

## Record

Implementation target:

```text
ItemMedia
  id
  item_id
  provider
  media_reference
  caption
  position
  created_at
  updated_at
```

Constraints:

- Item FK required;
- provider nonblank, bounded string;
- media_reference nonblank, bounded opaque string;
- caption nullable;
- position nonnegative integer;
- unique association per `(item_id, provider, media_reference)`;
- deterministic ordering by position then stable media-link ID.

Do not create a provider registry table for core MVP.

## Domain operations

Required inventory-side operations:

```text
attach_item_photo(item_id, provider, media_reference, caption?, position?)
list_item_photos(item_id)
update_item_photo(media_id, caption?, position?)
detach_item_photo(media_id)
```

Write operations resolve the parent Item by stable ID.

Detach deletes only the association; external bytes remain untouched.

Record structured Item Events:

- `item_photo_attached`;
- `item_photo_updated`;
- `item_photo_detached`.

Events preserve enough before/after data for history and immediate one-level compensation without retaining image bytes.

## Item lifecycle

- removed Item retains media associations;
- restore leaves associations unchanged;
- hard-delete does not exist;
- duplicate/equivalent lots each own independent association lists.

## Split rule

Media references are **not copied** to a split child.

Source/remainder keeps all existing photo references.

The split child begins with none.

No automatic media inference based on copied name/comment/attributes.

## Undo

Immediate one-level Undo should support:

- attach -> detach association;
- detach -> recreate the same association with prior metadata;
- caption/order update -> restore previous metadata.

Undo never calls external media delete.

## Web/API surface

Core application should expose structured media association endpoints and show references/captions in Item detail.

The web surface may render a resolved preview only when a configured external media resolver safely supplies one. Persistence/API correctness must not depend on resolver availability.

## External service boundary

The inventory application understands only:

```text
provider + media_reference
```

A separate media application/service owns:

- upload;
- byte storage;
- image MIME validation;
- thumbnails;
- byte retrieval;
- external delete/retention;
- optional future vision metadata.

If a resolver abstraction is implemented, keep it narrow, e.g.:

```text
resolve(provider, media_reference, purpose) -> display/fetch descriptor
```

Do not make external media availability part of database transactional correctness.

## Agent surface

Agent may:

- list attached photo references/captions;
- attach/detach when a trusted upstream adapter/user supplies an explicit media reference;
- edit caption/order.

Agent may not:

- invent media references;
- claim visual facts from a reference;
- request vision analysis in core MVP.

## Search

Do not index image content.

Caption search is optional and should be added only if it fits existing deterministic retrieval without weakening write-target safety.

## Portable/backup

- portable v3 does not carry ItemMedia references;
- full SQLite backup includes association rows;
- external media bytes require external backup.

No portable-v4 in this core batch.
