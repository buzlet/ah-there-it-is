# 0071 — ItemMedia schema and migration

Status: draft task spec; reconcile after 0061-0070 merge.

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
