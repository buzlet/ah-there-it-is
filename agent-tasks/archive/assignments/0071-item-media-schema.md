# 0071 — ItemMedia schema and migration

Status: issued implementation spec for batch 0071–0080.

## Objective

Add persistent one-to-many photo-reference associations without storing image bytes.

## Required model

Create an ItemMedia-style record with:

- stable integer id;
- item_id FK;
- provider: bounded nonblank string;
- media_reference: bounded nonblank opaque string;
- caption: nullable text;
- position: nonnegative integer;
- created_at / updated_at.

Constraints:

- unique (item_id, provider, media_reference);
- deterministic order by position then id;
- deleting/removing an Item through normal lifecycle does not cascade external media deletion;
- ordinary Item hard delete still does not become a product feature.

## Migration

- one Alembic head;
- upgrade populated and fresh DB;
- installed-wheel migration discovery;
- backup/restore remains valid;
- no image/blob column.

## Scope

Do not implement external media storage, vision, Telegram photo ingestion or portable format changes.

## Focused verification

Create focused migration/model tests for constraints, fresh/upgrade DB and removed-Item retention.


## Issued implementation constraints

- Keep this migration focused on ItemMedia persistence only.
- Do not add image bytes, thumbnails, vision metadata, provider registry tables or portable-format fields.
- Use bounded nonblank provider/reference fields and a database uniqueness constraint for one association per (item_id, provider, media_reference).
- Removed Item lifecycle must not delete associations.
- Physical DB cascade behavior, if used for exceptional administrative deletion, must never call an external media service.

## Focused verification

Create/extend `tests/test_item_media.py`.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_item_media.py tests/test_migrations.py tests/test_wheel_migrations.py -k "media or item_media or migration"
    make migration-check
    make compile
    git diff --check
