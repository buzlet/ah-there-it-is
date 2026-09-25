# 0070 — quantity lifecycle runtime integration

## Objective

Close cross-surface integration for the 0061–0069 implementation before final batch verification.

## Runtime surfaces

Audit and correct all active runtime projections and views so they understand:

- quantity_mode and nullable quantity;
- removed state/removal reason;
- active vs removed lifecycle filters;
- restore;
- equivalent lots;
- new Event types and quantity/split/removal details.

Remove obsolete assumptions that quantity is always an integer or that sold/discarded are active runtime terminal choices.

Historical sold/discarded Event display may remain historical.

## Operational compatibility

Verify:

- fresh database migration/bootstrap;
- upgrade from the pre-0061 schema;
- installed-wheel migration discovery;
- doctor/FTS consistency with unknown quantities and removed Items;
- backup/restore/rehearsal of the new schema;
- runtime CLI portable-v3 behavior;
- activity/history rendering of new Events;
- manual web item create/edit/move/remove/restore paths.

No backup scheduler/retention feature is added.

## Documentation/status

Update active project docs to describe the implemented runtime truth after this batch. Do not mark optional Telegram/photos/provider promotion as implemented.

Keep accepted design documents as historical implementation authority rather than rewriting their decisions.

## Legacy audit

Outside frozen v1/v2 import compatibility, migration code and historical Event rendering, obsolete runtime sold/discarded transitions must not remain reachable as first-class operations.

## Focused verification

    .venv/bin/python -m pytest -q tests/test_app.py tests/test_manual_admin.py tests/test_activity.py tests/test_runtime_cli.py tests/test_database_doctor.py tests/test_storage.py tests/test_restore_rehearsal.py tests/test_migrations.py tests/test_wheel_migrations.py -k "item or quantity or removed or restore or portable or migration or backup or restore"
    just compile
    git diff --check
