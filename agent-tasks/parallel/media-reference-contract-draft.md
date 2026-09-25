# Item media-reference contract draft

Status: optional post-MVP design draft. Not implementation authority.

## Goal

Allow one Item to be associated with zero, one or many photos while keeping media storage and image understanding outside the inventory core.

## Boundary

Inventory should store a reference plus minimal metadata, not image bytes.

Conceptual record:

```text
ItemMedia
  id
  item_id
  media_reference
  media_type
  caption/comment
  created_at
```

The exact schema is intentionally deferred.

## Requirements

- one Item may have multiple media references;
- deleting/removing an Item from active inventory does not implicitly destroy external media;
- stable Item ID is the association key on the inventory side;
- media_reference is opaque to inventory business logic;
- inventory must not infer filesystem/cloud-provider semantics from the reference;
- a future media adapter/service is responsible for storing/retrieving bytes;
- vision/model analysis is separate from attachment storage.

## Candidate external operations

A future media service may expose operations conceptually equivalent to:

```text
store_media(bytes/stream, metadata) -> media_reference
get_media(media_reference) -> media
delete_media(media_reference)       # external lifecycle, not inventory purge
```

Inventory needs only attachment-management operations such as:

```text
attach_media(item_id, media_reference, caption?)
detach_media(item_id, media_reference)
list_media(item_id)
```

## Open implementation choices for later

Not blockers for MVP:

- whether ItemMedia is its own table or a constrained JSON/reference list;
- whether references are URI-like strings or provider+opaque-id pairs;
- thumbnail handling;
- external media garbage collection;
- whether Telegram-origin images can be attached directly;
- whether captions are user text only or may include generated descriptions.

Do not choose these until the media service boundary is concrete.
