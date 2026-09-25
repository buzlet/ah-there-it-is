# 0073 — Item photo agent/web surfaces and Undo

Status: draft task spec; reconcile after 0061-0070 merge.

## Objective

Expose ItemMedia associations through structured application surfaces and integrate them with the already-implemented immediate one-level Undo.

## Agent/API

Add safe operations to:

- list Item photos;
- attach an explicit provider/reference;
- edit caption/order;
- detach a selected association.

The LLM may not invent references or claim visual facts from them.

## Web/manual surface

- Item detail shows attached photo references/captions in deterministic order;
- REST endpoints support attach/list/update/detach;
- validation is shared with domain service;
- resolver availability is not required for persistence correctness.

An optional media-resolver seam may be introduced, with a fake/test implementation, but no concrete external storage service is required.

## Undo

Immediate Undo supports:

- attach -> detach;
- detach -> recreate exact prior association;
- caption/order update -> restore prior values.

Compensation never deletes external media.

## Search/portable

- no image-content indexing;
- no vision;
- no portable-v4;
- portable-v3 remains unchanged and excludes ItemMedia references by accepted design.
