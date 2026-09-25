# 0061 — quantity and removed schema migration

## Objective

Create the persistent schema and migration foundation for the accepted quantity and lifecycle model without yet exposing the new application operations.

## Required changes

- Add a controlled quantity mode with values exact, approximate, unknown.
- Item quantity becomes nullable only for unknown mode.
- Add Item removal_reason as nullable text.
- Add runtime Item state removed.
- Migrate every existing Item quantity to quantity_mode=exact without changing its numeric value.
- Migrate existing sold Items to removed and preserve a deterministic sale reason.
- Migrate existing discarded Items to removed and preserve a deterministic discard reason.
- Preserve existing historical item_sold / item_discarded Events unchanged.
- Preserve existing terminal location truth: removed Items have no current location and location_status=not_applicable.
- Add database constraints sufficient to reject:
  - exact/approximate with null or nonpositive quantity;
  - unknown with non-null quantity.
- Do not introduce quantity=0 as a representation.

## Migration safety

- Keep exactly one Alembic head.
- Upgrade an existing populated database and a fresh database.
- Downgrade must not silently invent old semantics for new unrepresentable data.
- An immediate upgrade/downgrade roundtrip from the pre-batch schema must remain representable.
- Installed-wheel migration discovery must include the new revision.

## Runtime boundary

Do not yet implement split, partial move, generic remove/restore, portable-v3 or Undo in this task.

Legacy sold/discarded values may remain only where needed to read frozen historical/portable data; they are not accepted as the new runtime lifecycle.

## Focused verification

    .venv/bin/python -m pytest -q tests/test_migrations.py tests/test_wheel_migrations.py -k "quantity or removed or sold or discarded"
    just migration-check
    just compile
    git diff --check
