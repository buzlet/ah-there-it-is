# 0064 — removed/restore lifecycle and equivalent lots

## Objective

Replace runtime sold/discarded lifecycle operations with one user-intentional removed state and implement restore plus the accepted equivalent-lot policy.

## Removal

Add a generic remove_item operation.

Whole removal:

- requires explicit caller intent;
- keeps the same stable Item ID;
- preserves the Item's last meaningful quantity mode/value;
- clears current location;
- sets location_status=not_applicable;
- sets state=removed;
- stores nonblank removal_reason on Item;
- records original_text, reason and reason_source in a structured Event.

Partial removal:

- uses the 0063 internal split;
- leaves source active;
- marks only the child removed;
- is atomic with the split.

Arithmetic alone must never call remove_item automatically.

## Restore

Add restore_item for a removed Item:

- same stable ID;
- caller provides a nonterminal target state and explicit Location or explicit unknown location;
- clears current removal_reason after preserving it in the restore Event;
- restores correct location_status;
- no new Item is created.

## Runtime state cleanup

- New runtime operations do not create sold/discarded states.
- Replace model-facing sold/discard/reactivate concepts with remove/restore.
- Historical Events remain unchanged.
- Narrow compatibility shims are allowed only if an already-public surface requires them; any shim must map to removed and must not reintroduce sold/discarded runtime state.

## Equivalent lots

Equivalent duplicate Items are valid first-class records.

- Keep accidental duplicate protection as service policy.
- Internal split always permits an equivalent child.
- Explicit user intent to create a separate lot may bypass the ordinary duplicate warning/check.
- Name/category/location are not identity.
- Existing stable-ID write-target safety remains mandatory.

Update catalog lifecycle filtering so active vs removed is coherent.

## Focused verification

Create tests/test_removed_lifecycle.py.

    .venv/bin/python -m pytest -q tests/test_removed_lifecycle.py tests/test_domain.py tests/test_app.py -k "removed or restore or lifecycle or duplicate or equivalent"
    just compile
    git diff --check
