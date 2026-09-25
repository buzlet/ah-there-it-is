# 0072 — Item photo domain service and history

Status: draft task spec; reconcile after 0061-0070 merge.

## Objective

Implement inventory-side attachment operations and Event history.

## Operations

- attach_item_photo(item_id, provider, media_reference, caption?, position?);
- list_item_photos(item_id);
- update_item_photo(media_id, caption?, position?);
- detach_item_photo(media_id).

## Semantics

- stable Item ID resolution;
- explicit duplicate attachment rejection;
- detach removes only the association row;
- external bytes are never deleted;
- removed Items retain/list media;
- restore leaves media untouched;
- equivalent lots own independent media lists.

## Split invariant

When an Item is split:

- source/remainder retains all media references;
- child receives none;
- no inference/copy based on name/comment/attributes.

Add a regression test directly against the split code delivered by 0061-0070.

## Events

Create structured:

- item_photo_attached;
- item_photo_updated;
- item_photo_detached.

Payloads preserve enough association before/after metadata for history and later one-level compensation.

No image bytes in Event payloads.
