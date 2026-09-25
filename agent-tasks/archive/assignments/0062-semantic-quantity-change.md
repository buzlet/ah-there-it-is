# 0062 — semantic quantity value and change operation

## Objective

Make quantity truth explicit in the domain and replace generic scalar quantity editing with one semantic quantity-change operation.

## Quantity value contract

Represent:

- exact N, N >= 1;
- approximate N, N >= 1;
- unknown with no numeric value.

Use one validated domain representation shared by service/API layers where practical.

Creation defaults remain exact 1 unless the caller explicitly supplies another valid quantity state.

## Semantic mutation

Add one operation, conceptually change_item_quantity, which may change both quantity mode and value in one mutation.

It must:

- validate the full requested after-state before mutation;
- reject zero/negative or contradictory mode/value pairs;
- preserve original_text;
- require a nonblank compact reason;
- record reason_source as explicit or context;
- create a structured quantity-change Event containing before and after mode/value, reason and reason_source;
- produce no mutation Event for a true no-op.

Examples that must work:

- exact 20 -> exact 15;
- exact 20 -> approximate 15;
- exact 20 -> unknown;
- unknown -> approximate 50;
- approximate 50 -> exact 47;
- exact 47 -> unknown.

## Generic editing

Remove quantity from the unconstrained generic Item metadata update path. Callers that want to change quantity must use the semantic quantity operation.

Do not infer removal merely because a requested count would conceptually reach zero; zero is not a valid after-state for this operation.

## Compatibility

Update projections/domain helpers so nullable quantity is safe everywhere, but do not yet add partial split behavior.

## Focused verification

Create focused tests in tests/test_quantity_semantics.py.

    .venv/bin/python -m pytest -q tests/test_quantity_semantics.py tests/test_domain.py -k "quantity"
    just compile
    git diff --check
