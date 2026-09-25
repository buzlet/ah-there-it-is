# Quantity and physical-instance decision

Status: **accepted and closed** on 2026-09-25.

This document is implementation authority for the next quantity/physical-instance stage. The product-semantic gate is closed. Implementation may choose schema/API mechanics only where this document leaves them intentionally unspecified; it must not change the semantics below by inference.

## Context

The current model has one `quantity`, one state, one current-location truth, one category and one set of descriptive metadata per `Item`. That works only while every physical unit represented by an Item shares the same relevant inventory truth.

The goal is a personal inventory, not a warehouse system. The model should remain natural for statements such as:

- "There are about 50 screws in this box."
- "I moved 10 of them to the garage."
- "I no longer know how many remain."
- "Stop tracking this lot."
- "Split this cable entry; I'll keep the lengths in the comments."

## Alternatives considered

### A. One Item per physical object

Every physical object has its own stable Item ID and quantity is effectively always 1.

Advantages:

- simplest physical identity;
- independent location/state/history;
- no split required for partial operations.

Rejected because it is impractical for interchangeable household supplies such as screws, batteries, cables and other repeated units. It would create many indistinguishable Items and noisy retrieval.

### B. One aggregate Item for all identical goods

One Item represents all equivalent units regardless of location/state.

Advantages:

- simple total counting;
- few records.

Rejected because a single Item has only one current location/status/state. The model becomes false as soon as equivalent units are distributed across locations or only a subset changes state.

### C. Homogeneous physical lot

One Item represents either one physical object or a homogeneous group of interchangeable physical units that currently share the same modeled inventory truth.

Advantages:

- `quantity=1` still represents an individually tracked object;
- repeated fungible units remain compact;
- one-location/one-state Item semantics remain meaningful;
- partial operations become explicit split operations internally;
- no Product/SKU layer is required.

**Accepted.**

### D. Product plus instances/lots/stock positions

Separate Product/SKU identity from physical instances or stock positions.

Advantages:

- normalized warehouse-style model;
- clean separation between product description and stock.

Rejected for the current product because the added schema, retrieval, mutation and UX complexity is not justified by the target personal-inventory scale.

## Item semantics

An `Item` is a **homogeneous physical lot**.

It may represent:

- one distinguishable physical object; or
- multiple interchangeable physical units.

All units in one Item share the Item-level facts the application models, including:

- current location/location status;
- state;
- category;
- common descriptive metadata.

If only part of a lot must acquire a different modeled location or state, that part becomes a separate Item through an internal split.

The system does not attempt to prove interchangeability automatically. This is a user/domain semantic contract.

## Quantity representation

Quantity means the current number of physical units represented by the Item. It does not mean lifetime acquisitions, package size or arbitrary continuous measurement such as meters or liters.

Accepted precision modes:

- `exact` — exact unit count is known;
- `approximate` — a useful approximate unit count is known;
- `unknown` — the Item exists and represents a nonzero amount, but no useful numeric count is known.

Conceptually:

```text
quantity_mode = exact | approximate | unknown
quantity      = integer >= 1 | null
```

Required invariants:

- `exact` -> integer `quantity >= 1`;
- `approximate` -> integer `quantity >= 1`;
- `unknown` -> `quantity = null`;
- `quantity=0` is never stored;
- an existing active `unknown` Item means some nonzero amount exists;
- `many` is presentation language, not another machine state.

## One semantic quantity-change operation

There is one semantic operation for changing recorded quantity knowledge. It may change both the numeric value and its precision mode in one mutation.

Examples:

```text
exact 20        -> exact 15
exact 20        -> approximate 15
exact 20        -> unknown
unknown         -> approximate 50
approximate 50  -> exact 47
exact 47        -> unknown
```

The generic Item metadata editor must not remain an unconstrained way to rewrite quantity.

Each quantity-change Event preserves:

- before value/mode;
- after value/mode;
- the user's original text when available;
- a compact textual reason;
- whether the reason was explicit in the user's words or derived from conversation context.

Conceptually:

```text
reason_source = explicit | context
```

The agent may formulate a reason from unambiguous context when the user did not restate it. It must not invent a reason that the conversation does not support.

## Approximate arithmetic and loss of precision

When the user supplies a usable amount, the system performs the arithmetic rather than refusing merely because the source is approximate.

Examples:

```text
exact 20       - exact 5        -> exact 15
approximate 20 - exact 5        -> approximate 15
approximate 20 - approximate 5  -> approximate 15
unknown        - exact 5        -> unknown
```

If approximate arithmetic produces a remainder of zero or less, the system does **not** infer that the lot is exhausted. The remainder becomes `unknown` unless the user explicitly said that all remaining units were affected.

Example:

```text
approximate 5 - exact 7 -> unknown
```

The user is informed that the previous estimate was inconsistent with the operation and the remainder is now unknown.

If the source was exact but the user requests a partial operation without enough information to preserve an exact count (for example "move some"), the operation should still be performed when the target and action are clear. The affected child and/or remainder may lose precision to `unknown` rather than blocking on a quantity clarification.

Quantity ambiguity is therefore normally **non-blocking**. The agent performs a safe representation first, then may ask for or suggest a later refinement.

The exception is ambiguity about the mutation target or the requested action itself; existing write-target safety still applies.

## Partial operations and split

Partial move/take/removal is represented internally by splitting the source lot and applying the requested whole-lot operation to the separated child.

Example:

```text
before:
  Item 100, screws, exact 20, Workshop

"Move 5 to Backpack"

after:
  Item 100, screws, exact 15, Workshop
  Item 201, screws, exact 5, Backpack
```

Identity rules:

- whole-Item operations preserve the existing stable Item ID;
- on split, the source/remainder keeps its stable Item ID;
- the separated child receives a new stable Item ID;
- the split and requested partial operation are one atomic domain transaction;
- the LLM is not required to orchestrate a low-level split followed by another mutation.

Split provenance uses structured Event history in the simplified model. No separate lineage table is introduced at this stage.

The split Event must record enough structured information to relate source and child stable IDs and the before/after quantity states.

## High-level API/tool shape

The preferred model-facing interface expresses user intent directly.

Conceptually:

```text
move_item(item_id=10, location_id=7, quantity=5)
remove_item(item_id=10, quantity=2, reason="gave to neighbor")
take_item(item_id=10, quantity=1)
```

When `quantity` is omitted, the operation applies to the whole Item.

When a partial quantity is supplied, the domain service performs the required split internally and atomically.

A low-level `split_item` primitive may exist internally for service code/tests, but it should not be necessary as a normal LLM tool. This reduces tool-round coupling, intermediate-ID mistakes and model-specific orchestration.

## Equivalent/duplicate lots

Equivalent Items are valid first-class records. Merge is not implemented.

The system must not enforce identity through human-visible name, category or location.

Creation policy:

- ordinary creation should still search/check for an existing equivalent candidate and avoid accidental duplication;
- an explicit user intention to create a separate lot permits another equivalent Item;
- internal split always permits creation of the equivalent child;
- write mutation of an existing Item still requires stable-ID resolution and the existing strong write-target evidence.

This preserves duplicate protection as a service policy without making duplicate-name lots impossible.

## Merge

**Not implemented.**

Several equivalent Items may remain separate indefinitely, even in the same location.

This is intentionally acceptable. No supersession/absorption identity graph is required.

## Removal from inventory

The product uses one generic terminal lifecycle concept:

```text
removed
```

It replaces the need for separate future terminal semantics such as sold, discarded, consumed, given away, lost, donated, etc.

Removal means:

> the user intentionally stopped tracking this Item as part of the active inventory.

The reason is data, not a state enum.

Examples:

```text
reason = "sold"
reason = "thrown away"
reason = "used up"
reason = "gave to neighbor"
reason = "lost"
reason = "replaced by separately tracked components"
reason = "user stopped tracking it"
```

The removal reason is stored on the removed Item for direct display/search and is also preserved in the removal Event with original user text and reason source.

### Removal must be user-intentional

The agent must not mark an Item `removed` merely because arithmetic reaches zero.

The intent to stop tracking the lot must come from the user's explicit request or an unambiguous user instruction in context.

Examples that support removal:

- "used all the remaining screws";
- "sold all five";
- "throw this away";
- "stop tracking this";
- "remove this position from inventory."

A bare arithmetic statement that does not establish removal intent must not silently terminate the Item.

### Quantity on a removed Item

Removal never stores zero.

The Item retains the quantity state that describes the lot at the moment it was removed.

Example:

```text
before:
  Item 25, screws, exact 5

after "used the last five; stop tracking them":
  Item 25, state=removed, quantity_mode=exact, quantity=5
  removal_reason="used the last five"
```

For an unknown lot, removal retains `unknown`.

### Partial removal

Partial removal is an internal split followed by removal of the child.

Example:

```text
before:
  Item 10, screws, exact 20

"gave 10 to neighbor"

after:
  Item 10, active, exact 10
  Item 31, removed, exact 10, reason="gave to neighbor"
```

### Restore

A removed Item may be returned to active inventory using the same stable ID when the user is referring to the same logical Item/lot.

Conceptually this replaces the old narrow sold/discarded reactivation semantics with a generic restore/return-to-inventory operation.

The user may instead deliberately keep the old Item removed and create one or more new Items when changing the way something is tracked. No automatic lineage between the old and new representations is required.

## Migration from current sold/discarded states

The current runtime still has separate `sold` and `discarded` states until this decision is implemented.

During migration:

- existing `sold` Items map to `removed` with a preserved reason indicating sale;
- existing `discarded` Items map to `removed` with a preserved reason indicating discard;
- historical `item_sold` / `item_discarded` Events remain historical evidence and are not rewritten merely to rename the new state machine;
- nonterminal states continue normally;
- legacy integer quantities map deterministically to `quantity_mode=exact`.

## Comments and non-modeled measurements

The existing Item free-text description/comment is the escape hatch for useful facts that the formal domain does not model.

Split copies the source description/comment to the child by default. The user can edit either copy independently afterwards.

Example:

```text
before:
  Item 15: Cable
  exact 1
  comment: "About 30 meters"

after split:
  Item 15: Cable, exact 1, comment: "About 30 meters"
  Item 42: Cable, exact 1, comment: "About 30 meters"
```

The user may then change the comments to "about 20 meters" and "about 10 meters".

Consequences:

- meters, liters, kilograms, percentages, "half a box", ranges and similar measurements are not formal quantity units at this stage;
- the system does not maintain arithmetic invariants for facts embedded in comments;
- comment text is not promoted into authoritative structured truth without a user-supported fact;
- formal measurement units may be added later only if real operations/search requirements justify them.

### Comment contradictions after split

A copied comment may become semantically suspicious after a split, for example when both resulting Items say "30 meters".

This is not a database invariant violation and must not roll back an otherwise valid split.

The agent should inspect the resulting Items and context:

- if the copied comment is still non-contradictory, no extra user-facing action is required;
- if it creates a visible contradiction or ambiguity, the agent should show the relevant data and suggest or ask for a correction;
- if enough information is already present in the user's instruction, the agent may update the comments in the same logical turn rather than asking first.

The default interaction principle is **perform safely first, clarify/refine afterwards**, unless write-target/action ambiguity prevents a safe mutation.

## Metadata copied by split

Default behavior:

- name: copied;
- description/comment: copied;
- category: copied;
- aliases: copied;
- tags: copied;
- attributes: copied;
- state: copied initially;
- location/location status: copied initially;
- quantity value/precision: derived from split semantics, not blindly copied;
- stable ID: never copied.

The child may immediately diverge as part of the requested operation.

## User-visible receipts and presentation

Backend mutation receipts should remain rich enough for verification and agent reasoning, including stable IDs, before/after quantity precision, split results, location/state changes and copied-comment facts.

The product does **not** require a fixed verbose user-facing receipt.

The agent decides how much to show from the structured result according to the user's request and preferences.

Typical successful output may be as short as:

> Moved 5 batteries to the car.

Additional details are surfaced when useful, especially when precision was lost, an estimate was inconsistent, or copied comments became ambiguous.

Search/list presentation follows the same principle: backend results provide stable ID, quantity precision/value, location, state and comment context, while the agent chooses the user-facing form.

## Portable format

Portable format is the logical JSON inventory interchange format, distinct from a full SQLite backup.

Because the new quantity model permits both a precision mode and `quantity=null`, it changes the portable contract rather than merely adding an optional annotation.

**Accepted:** introduce `inventory-portable-v3`.

Compatibility policy:

- new exports use v3;
- imports continue to accept frozen v1 and v2;
- v1/v2 integer quantity maps to v3 `quantity_mode=exact`;
- v1/v2 compatibility must not be silently weakened.

## Explicit non-goals

This decision does not introduce:

- Item merge;
- Product/SKU entities;
- continuous measurement units;
- automatic arithmetic over free-text comments;
- automatic parsing of comments into structured quantity truth;
- hard deletion of historical Items;
- automatic removal merely because a numeric calculation reaches zero;
- a separate lineage graph/table for split;
- generic Undo semantics.

## Decision summary

The quantity/physical-instance product gate is closed.

Accepted implementation semantics:

1. Item is a homogeneous physical lot.
2. Quantity precision is `exact | approximate | unknown`.
3. Zero quantity is never stored.
4. One semantic quantity-change operation may change both value and precision and records original text plus explicit/context reason.
5. Approximate arithmetic is performed; inconsistent/nonpositive approximate remainders become `unknown` unless the user explicitly indicates "all".
6. Quantity ambiguity normally does not block an otherwise safe operation; perform first and expose/refine uncertainty afterwards.
7. Partial high-level operations split internally and atomically; the remainder keeps its stable ID and the child gets a new ID.
8. Split provenance is stored in structured Event history; no separate lineage table.
9. Equivalent lots are allowed; accidental duplicate creation remains guarded by service policy.
10. Merge is not implemented.
11. `removed` is the single generic terminal lifecycle state, with a textual reason stored on Item and Event.
12. Removal requires user intent and is never inferred solely from arithmetic.
13. Removed Items retain their last meaningful quantity rather than storing zero.
14. Removed Items can be restored under the same stable ID when appropriate.
15. Split copies comments and descriptive metadata; comments remain the escape hatch for non-modeled measurements.
16. Backend receipts are structured and rich; user-facing presentation remains agent-driven.
17. Portable export advances to v3; v1/v2 import quantities map to `exact`.
18. Existing sold/discarded data migrates to `removed` without rewriting historical Events.

The next step is implementation planning and batching, not further product-semantic design.
