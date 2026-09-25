# 0065 — agent/web quantity interfaces and durable receipts

## Objective

Expose the accepted quantity/lifecycle operations through model-facing and manual web contracts while enriching backend-owned receipts enough for later one-level Undo.

## Item projections

All relevant structured Item responses expose:

- quantity_mode;
- nullable quantity;
- removal_reason;
- existing stable ID/state/location truth/comment metadata.

## Agent tools

Replace/extend model-facing contracts so the model can express user intent directly:

- create Item with exact/approximate/unknown quantity;
- change Item quantity through the semantic quantity-change tool with reason and reason_source;
- move/take with an optional explicit portion object;
- remove with optional portion plus reason/reason_source;
- restore a removed Item.

Do not expose a required low-level split_item choreography.

Remove quantity from generic update_item.

Legacy sold/discard/reactivate tools must not remain first-class model-facing lifecycle operations.

## Manual web/API

Add equivalent safe request/response support for the new quantity state and generic remove/restore lifecycle. Manual UI/API must not store invalid mode/value combinations.

Do not add a user/channel/account model.

## Durable mutation receipts

Extend MutationReceipt or the durable per-run journal representation with enough backend-owned structured evidence for:

- affected stable Item IDs, including split child IDs;
- operation kind;
- before/after quantity mode/value when changed;
- before/after state/location/location_status/removal_reason as relevant;
- copied-comment/split facts needed by the agent;
- expected post-state facts needed to fail closed during Undo;
- operation-specific compensation metadata where generic inversion would be unsafe.

Keep receipts bounded to facts for the mutation turn; do not snapshot unrelated inventory.

Existing successful-turn transactional behavior remains unchanged.

## Provider contract

Tool schemas changed; provider-contract verification is required.

## Focused verification

    .venv/bin/python -m pytest -q tests/test_agent.py tests/test_app.py tests/test_atomic_turn_receipts.py -k "quantity or partial or removed or restore or receipt"
    just provider-contract
    just compile
    git diff --check
