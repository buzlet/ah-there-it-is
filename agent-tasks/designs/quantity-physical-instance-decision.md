# Quantity and physical-instance decision

Status: accepted product-semantic decision on 2026-09-25. This document is implementation authority for the decisions marked **Accepted** below. The remaining open questions at the end must be resolved before issuing the implementation batch.

## Context

The current `Item` model has one `quantity`, one state, one current-location truth, one category and one set of descriptive metadata. Whole-item move/take/sell/discard/reactivate operations already act on that single Item.

That model is correct only while every physical unit represented by an Item shares the same relevant inventory truth. Partial operations therefore require an explicit semantic model rather than treating `quantity` as an arbitrary editable counter.

## Alternatives considered

### A. One Item per physical object

Every physical object would have its own stable Item ID and `quantity` would effectively always be 1.

Advantages:

- simplest identity and history semantics;
- location/state always belong to one concrete object;
- partial operations need no split.

Rejected because it is impractical for household inventory containing many interchangeable units such as screws, batteries, cables, cups or other repeated supplies. It would create large numbers of indistinguishable Items and noisy search results.

### B. One aggregate Item for all identical goods

One Item would represent all equivalent units regardless of location/state.

Advantages:

- simple total counting;
- few Item records.

Rejected because one Item has only one current location/status/state. As soon as identical units are in different locations, or only some are sold/discarded/in use, the aggregate can no longer represent the truth without introducing a second stock-position model.

### C. Homogeneous lot

One Item represents either one physical object or a homogeneous group of interchangeable physical units that currently share the same relevant inventory truth.

Advantages:

- `quantity=1` naturally represents individually tracked objects;
- large fungible groups remain compact;
- current one-location/one-state Item model remains meaningful;
- partial operations can be expressed by splitting a lot;
- does not require a separate Product/SKU layer.

**Accepted.**

### D. Product plus instances/lots/stock positions

Introduce a separate Product/SKU identity and separate physical-instance or stock-position records.

Advantages:

- most normalized long-term warehouse model;
- clean separation between product description and physical stock.

Rejected for the current product because it adds substantial schema, search, mutation and UX complexity without demonstrated need for a personal inventory of the target scale.

## Accepted Item semantics

An `Item` is a **homogeneous physical lot**.

It may represent:

- one distinguishable physical object (`quantity=1`); or
- multiple interchangeable physical units.

All units represented by one Item must share the inventory facts that the system models on Item level, including:

- current location/location status;
- state;
- category;
- descriptive metadata insofar as the user considers it common to the lot.

If part of the lot must acquire a different modeled state or location, that part becomes a separate Item through split.

The system does not need to prove physical interchangeability automatically. This is a user/domain semantic contract.

## Quantity semantics

**Accepted:** quantity describes the current number of physical units represented by the Item, not lifetime acquisition count, package size or an arbitrary measurement such as meters/liters.

Quantity has three precision modes:

- `exact` — the user/system knows the exact unit count;
- `approximate` — a useful approximate unit count is known;
- `unknown` — the Item exists and represents a nonzero amount, but no useful unit count is known.

Conceptually:

```text
quantity_mode = exact | approximate | unknown
quantity      = integer >= 1 | null
```

Required meaning:

- `exact` -> `quantity >= 1`;
- `approximate` -> `quantity >= 1`;
- `unknown` -> `quantity = null`;
- no Item record represents zero units;
- an existing `unknown` Item means that some nonzero amount exists;
- `many` is not a separate machine state; it is user-facing wording that can be represented by `unknown` plus a comment.

The current generic Item-edit operation must not remain an unconstrained way to rewrite quantity. Quantity changes need semantic operations so Event history records what happened rather than only `N -> M`.

## Partial operations and split

**Accepted:** partial move/take/sale/disposal is represented by splitting the source Item and then applying the ordinary whole-Item operation to the separated Item.

Example:

```text
before:
  Item 100, screws, exact 20, Workshop

"Move 5 to Backpack"

after split:
  Item 100, screws, exact 15, Workshop
  Item 201, screws, exact 5,  Workshop

after move:
  Item 100, screws, exact 15, Workshop
  Item 201, screws, exact 5,  Backpack
```

Identity rules:

- a whole-Item operation preserves the existing stable Item ID;
- on split, the source/remainder keeps its stable Item ID;
- the separated part receives a new stable Item ID;
- split must have explicit history/provenance linking the source and new Item;
- split must be transactionally atomic with the requested partial operation when invoked as one user action.

For an exact source and exact separated amount, exact quantity conservation is required.

For an unknown source:

- separating an exact number may create an exact child while the remainder stays unknown;
- separating an unspecified part may create an unknown child while the remainder stays unknown;
- moving/selling/discarding **all** of the unknown lot is a whole-Item operation and does not split.

The detailed arithmetic policy for `approximate` sources is intentionally left open below; implementation must not invent false precision.

## Merge

Several equivalent Items may coexist, including Items with the same human-visible name.

**Accepted:** Item merge is not implemented.

The application must tolerate separate equivalent lots rather than forcing normalization back into one Item. No absorbed/superseded identity semantics are needed for this stage.

## Comments and non-modeled measurements

The existing Item free-text description/comment is the escape hatch for useful facts that the domain does not formally model.

**Accepted:** split copies the source Item comment/description to the new Item by default.

The user is informed that the comment was copied and may then edit either Item independently.

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

The user may subsequently change the comments to, for example, "about 20 meters" and "about 10 meters".

Consequences:

- meters, liters, kilograms, percentages, "half a box", ranges and similar measurements are not formal quantity units in this stage;
- the system does not maintain arithmetic invariants for facts embedded in comments;
- the LLM/domain must not promote comment text into authoritative structured truth without a new explicit user fact;
- measurements may be formalized later only if real operations/search requirements justify it.

## Metadata copied by split

Accepted default behavior:

- name: copied;
- description/comment: copied;
- category: copied;
- aliases: copied;
- tags: copied;
- attributes: copied;
- state: copied;
- location/location status: copied initially;
- quantity precision/value: derived according to split semantics, not blindly copied;
- stable ID: never copied.

The separated Item can immediately diverge when the requested operation changes its location/state/comment/etc.

## Examples

### Uncounted screws

```text
Item 100
name = "Screw 4x30"
quantity_mode = unknown
quantity = null
comment = "About half a box"
location = Workshop / Box 3
```

"Put exactly 10 screws in the backpack" can produce:

```text
Item 100: unknown, Workshop / Box 3
Item 101: exact 10, Backpack
```

No attempt is made to infer the remaining exact count.

### Approximate count

```text
Item 200
name = "AA battery"
quantity_mode = approximate
quantity = 50
```

This means approximately 50 units, not exactly 50. A later explicit count may change it to `exact 47`.

### Lost precision

A user may explicitly state that a previously exact count is no longer trustworthy. The domain must be able to represent loss of precision, e.g. `exact 100 -> unknown`, with semantic history rather than silently retaining stale exact data.

## Explicit non-goals of this decision

This decision does not introduce:

- Item merge;
- Product/SKU entities;
- meters/liters/weights as formal quantity units;
- automatic parsing of comments into structured quantity;
- hard deletion of historical Items;
- generic Undo semantics.

## Open questions before implementation

The following remain to be decided and must not be guessed by an implementation agent:

1. **Approximate split arithmetic.** If an approximate lot `~N` loses an exact or approximate subset, should the remainder keep a derived approximate estimate, become unknown, or require an explicit user estimate?
2. **Quantity mutation vocabulary.** Define explicit operations for acquisition/addition, count correction, loss of precision and other non-split quantity changes; decide which operations need user-supplied reasons.
3. **Split lineage persistence.** Decide whether split provenance is represented only in Event payloads, with a dedicated relational lineage structure, or with another constrained schema. It must support reliable history without merge semantics.
4. **Duplicate Item policy.** Current name/category duplicate protection must be reconciled with intentionally separate equivalent lots. Decide when duplicate-name Items are first-class and how write-target resolution remains safe.
5. **Portable format evolution.** Current portable v2 has required integer quantity semantics. Decide whether this change requires portable v3 or another explicitly compatible representation; frozen v1 support must not be silently broken.
6. **Existing-data migration.** Existing integer quantities have to map deterministically into the new model, expected to mean `exact`, with DB constraints and migration behavior specified.
7. **Agent/API operation shape.** Decide whether partial operations expose a single atomic domain operation (for example partial move) that performs split internally, an explicit split tool followed by a whole-Item tool, or both at different layers.
8. **User-visible receipts.** Define what a split response must show: retained Item ID, new Item ID, quantities/precision, copied comment notice and the subsequent operation result.
9. **Unknown-lot wording.** Commands such as "some", "half", "ten", and "all" need deterministic interpretation/clarification rules so an unknown source is never accidentally exhausted or duplicated.
10. **Search/list presentation.** Equivalent separate lots must remain understandable in search results using stable ID plus location, quantity precision and comment context.

These are the remaining quantity-gate discussions. Merge itself is closed as a non-goal.
