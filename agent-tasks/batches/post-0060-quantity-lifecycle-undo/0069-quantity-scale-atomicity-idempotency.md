# 0069 — quantity lifecycle scale/atomicity/idempotency hardening

## Objective

Prove the new quantity/lifecycle paths remain safe at target scale and across failure/retry boundaries.

## Scale

Extend deterministic target-scale data with:

- roughly 1000 Items;
- a mixture of exact/approximate/unknown quantities;
- many equivalent lots;
- removed Items;
- repeated partial operations creating split children;
- substantial Event history.

Do not use wall-clock/RSS pass thresholds.

Search/list behavior must remain deterministic and bounded when multiple equivalent lots share names/categories/locations.

## Transaction failure

Add structural failure-injection coverage showing:

- split + move failure rolls back source quantity, child and Events;
- split + remove failure rolls back everything;
- quantity-change failure leaves before-state intact;
- Undo failure leaves the prior action intact and applies no subset of compensation.

## Idempotency

For keyed agent requests:

- partial operation replay does not create another split child;
- remove replay does not duplicate Events;
- Undo replay does not Undo twice;
- crash recovery semantics remain consistent with existing request-key rules.

## Write-target safety

Equivalent lots must increase ambiguity rather than weaken target safety.

Agent mutations continue to require resolved stable IDs and atomic revalidation. Do not choose a lot merely by duplicate name.

## Focused verification

    .venv/bin/python -m pytest -q tests/test_target_scale.py tests/test_atomic_turn_receipts.py tests/test_idempotency.py tests/test_idempotency_crash.py tests/test_write_target_safety.py -k "quantity or split or removed or undo or duplicate or equivalent"
    just compile
    git diff --check
