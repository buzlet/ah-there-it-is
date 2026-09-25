# Immediate one-level Undo and purge decision

Status: accepted product-semantic decision on 2026-09-25.

## Correction principle

Historical inventory Events are not rewritten as the normal correction mechanism.

A correction is ordinarily a new explicit mutation that records what changed. The user may simply state the corrected fact or reverse operation in natural language.

## Immediate one-level Undo

A deliberately narrow Undo is desirable and is part of the intended core behavior **provided it remains within the contract below**. This is not a general undo stack.

### User contract

Undo means:

> compensate the immediately preceding committed user action that changed inventory state.

Rules:

- one level only;
- no redo stack;
- the Undo request must be the next user action after the mutation being undone;
- read/write target safety remains authoritative;
- Undo never means "find some older action that looks related";
- if the immediately preceding action is not safely compensable under the supported contract, the system reports that and leaves data unchanged.

The unit of intent is the previous logical user mutation action, not an arbitrary latest low-level Event.

### Implementation direction

The existing application already commits one agent turn atomically and stores backend-owned mutation receipts on `AgentRunLog`.

Undo should build on that boundary, but current receipts are too compact to be blindly reversed. The implementation may extend durable receipt/journal data with the minimal before/after facts needed to construct a safe compensating mutation.

Undo is **compensating**, not history erasure:

- the original Events remain;
- the undo action creates new Events/receipts explaining the compensation;
- traces remain permanent;
- no previous Event is deleted or rewritten merely because it was undone.

The application must verify that the current state still matches the expected post-state of the immediately preceding action before applying compensation. If it does not, Undo fails closed.

### Supported Item behavior

Common Item mutations should be undoable through ordinary inverse domain operations where safe, including:

- whole-item move/location changes;
- take / return-to-location style transitions;
- Item metadata/comment changes when the previous value is durably known;
- semantic quantity changes when the previous quantity value/mode is durably known;
- generic `removed` / restore transitions;
- partial operations that internally created a split child.

### Split does not require merge on Undo

Undo of a partial operation does not require re-merging lots.

Example:

```text
before:
  Item 100: exact 20, Workshop

partial move 5:
  Item 100: exact 15, Workshop
  Item 201: exact 5, Backpack

immediate Undo:
  Item 100: exact 15, Workshop
  Item 201: exact 5, Workshop
```

The user-visible effect of the move is reversed. The two equivalent lots may remain separate, which is valid because:

- equivalent duplicate lots are first-class;
- merge is intentionally not implemented.

Likewise, undoing a partial removal may restore the removed child to active inventory without merging it back into the source lot.

### Creation and structural mutations

Undo does not gain a general hard-delete capability.

If exact reversal of a newly created Item can be represented safely through the accepted lifecycle (for example marking it removed with an undo reason), that may be supported.

Location/category creation or other structural changes must not be physically deleted merely to satisfy generic Undo unless a future explicit design extends this contract. If such an action cannot be safely compensated, one-level Undo may report it unsupported and the user can correct it through ordinary operations.

This limitation is acceptable; the goal is a safe convenience for common immediately mistaken inventory actions, not a universal database rollback mechanism.

### Multi-mutation previous turns

A previous user turn may contain more than one low-level mutation.

If the implementation declares that logical action undoable, compensation must be atomic and apply the supported inverse mutations in a dependency-safe order. Partial compensation is not allowed.

If the complete logical action cannot be compensated safely, Undo leaves it unchanged.

## Hard delete / destructive purge

The application does **not** implement ordinary hard delete or destructive purge of Items/history/traces.

The generic `removed` lifecycle state is the normal mechanism for stopping active inventory tracking.

Exceptional physical deletion for privacy/administrative purposes is outside product scope and may be handled externally only under a future explicit decision.

Immediate Undo does not change this policy and must not become a hidden generic purge API.

## Result

The correction/Undo and hard-delete/purge product gates are closed.

There is no remaining unresolved product-semantic decision required before quantity implementation planning.
