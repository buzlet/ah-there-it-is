# 0073 — Item photo agent/web surfaces and Undo

Status: issued implementation spec for batch 0071–0080.

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


## Issued implementation constraints

- Agent-facing tools accept only explicit provider/reference values supplied by trusted upstream/user context; never invent a reference.
- Web/manual endpoints must resolve the parent Item by stable ID.
- Immediate Undo is compensating history, not deletion of historical Events.
- Undo attach/detach/update must never call external media deletion.
- Portable-v3 stays byte/schema compatible with the current v3 contract.

## Focused verification

Keep media API/agent/Undo coverage in `tests/test_item_media.py` plus existing application/agent/Undo tests.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_item_media.py tests/test_app.py tests/test_agent.py tests/test_undo.py tests/test_atomic_turn_receipts.py -k "media or photo or undo"
    make provider-contract
    make compile
    git diff --check
