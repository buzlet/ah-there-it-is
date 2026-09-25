# 0066 — portable-v3 quantity/lifecycle compatibility

## Objective

Advance logical portable export to inventory-portable-v3 while preserving frozen v1/v2 import compatibility and the bounded streaming guarantees from 0051–0060.

## V3 Item contract

V3 must represent at least:

- quantity_mode;
- quantity nullable for unknown;
- state including removed;
- removal_reason when removed;
- existing Item/category/location/alias/tag/attribute/timestamp fields.

V3 must reject contradictory quantity mode/value pairs and contradictory removed location truth.

New exports use v3.

## Frozen legacy import

Continue to accept frozen v1 and v2 documents without changing their on-disk schema.

During import:

- legacy integer quantity => quantity_mode=exact;
- legacy sold => removed with deterministic preserved sale reason;
- legacy discarded => removed with deterministic preserved discard reason;
- legacy historical Event types remain historical Event data.

Do not use the new runtime ItemState enum as an accidental reason to reject legacy sold/discarded values in frozen parsers.

## Bounded pipeline

Integrate v3 into the existing streaming/bounded reader, validator and importer.

Do not regress to whole-file read_text/json.loads/one-complete-document materialization in the production import/dry-run path.

Preserve:

- duplicate-key rejection;
- strict extra-field behavior;
- arbitrary legal object ordering;
- reference/hierarchy validation;
- target publication race safety;
- one working transaction;
- cleanup on late failure;
- deterministic export;
- snapshot consistency.

## Compatibility

- v1/v2 import remains green;
- v3 export -> dry-run -> import -> re-export roundtrip preserves semantic data except defined volatile export timestamp;
- backup/restore remains separate from portable format.

## Focused verification

Create tests/test_portable_v3.py.

    .venv/bin/python -m pytest -q tests/test_portable_v3.py tests/test_portable_compatibility.py tests/test_portable_streaming_import.py tests/test_storage.py -k "portable or quantity or removed"
    just compile
    git diff --check
