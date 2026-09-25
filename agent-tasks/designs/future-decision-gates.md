# Future decision gates

Only unresolved product-semantic decisions are kept active here.

Resolved quantity/physical-instance semantics:
`agent-tasks/designs/quantity-physical-instance-decision.md`

Resolved deployment/integration/language scope:
`agent-tasks/designs/product-scope-decisions.md`

## Correction / undo

Preferred principle: corrections use explicit compensating mutations/Events rather than rewriting history.

Still unresolved:

- whether generic Undo exists at all;
- if it exists, which mutations are reversible through a user-facing Undo operation;
- how Undo interacts with split/removal/restore and later dependent mutations.

This is not required for the accepted quantity implementation unless generic Undo is declared part of core MVP.

## Hard delete / purge

Current principle: no ordinary hard delete. Historical Items and Events remain durable, including Items moved to the generic `removed` lifecycle state.

Still unresolved:

- whether an exceptional destructive purge feature should ever exist;
- if it exists, its privacy/safety semantics and relationship to historical Events/traces.

This is not required for normal inventory operation or the quantity implementation.
