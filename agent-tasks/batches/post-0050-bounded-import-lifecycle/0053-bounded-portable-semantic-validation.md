# Assignment 0053: bounded portable semantic validation

## Objective

Move portable-v1/v2 structural and semantic validation onto the streaming/spooled representation without reconstructing one complete `PortableDocument`.

## Required behavior

- Preserve frozen `inventory-portable-v1` import compatibility and current `inventory-portable-v2` semantics.
- Validate scalar/top-level metadata strictly, including format dispatch, source revision, timestamps, excluded entries and unknown/extra fields.
- Validate every category/location/item/event record through the current strict typed rules or equivalent per-record Pydantic validation.
- Preserve all current semantic checks:
  - positive/unique stable IDs;
  - nonblank normalized names;
  - created/updated ordering;
  - valid state/location-status combinations;
  - category/location parent references and no self-parent;
  - sibling normalized-name uniqueness;
  - hierarchy cycle rejection;
  - item category/location references;
  - alias/tag normalized duplicates;
  - cross-item normalized tag spelling consistency;
  - event item/location references;
  - v1 conservative location-status derivation.
- Heavy item/event payload objects must not be retained after their validation pass.
- Compact indexes such as ID sets, tree parent maps and normalized-name maps are acceptable. Their purpose must be reference/identity validation, not caching the source document.
- Use a second pass over disk-backed spools when necessary so forward references and arbitrary JSON member/array ordering remain valid.
- Produce a typed compact summary containing format, source revision and exact category/location/item/event counts for later import/dry-run use.
- Validation failure must occur before any application destination or migrated working database is created.

## Compatibility requirement

Existing pure `parse_portable_inventory()` / `load_portable_inventory()` helpers may remain for direct compatibility/unit use, but the new bounded production import/dry-run path must not depend on constructing their complete document result.

## Constraints

No database writes, schema changes, weakened validation, format evolution, dependencies or product semantics.

## Focused verification

Use the manifest-declared 0053 check only.
