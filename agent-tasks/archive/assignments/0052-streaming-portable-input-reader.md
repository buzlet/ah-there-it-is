# Assignment 0052: streaming portable input reader

## Objective

Introduce the bounded input boundary needed for portable import.

The production import path currently begins with `Path.read_text()` + whole-document `json.loads()`, so export is streaming but import is not.

This assignment builds the reader/spooling layer only. It does not write the application database yet.

## Required behavior

- Add an internal standard-library-only streaming portable JSON reader/workspace.
- The reader must consume the source through bounded reads; production streaming code must not call `Path.read_text()`, `json.load()`, or whole-document `json.loads()`.
- JSON object member order is non-semantic. Accept valid portable documents even when top-level members, `inventory` members, or `history` members appear in a different order from the exporter.
- Preserve strict JSON behavior:
  - malformed JSON fails;
  - invalid UTF-8/read errors fail clearly;
  - duplicate object keys are rejected at every object depth before duplicate information can be lost.
- Retain only bounded parser state plus one current element/chunk in Python for large arrays.
- Large arrays for categories, locations, items and events may be spooled to an isolated temporary workspace for later passes. Disk-backed spooling is allowed and preferred over keeping heavyweight Python objects.
- Temporary workspace/files must be cleaned after both success and failure.
- Preserve enough source/path context to report useful validation locations in later tasks.
- Do not require canonical exporter key ordering.

## Structural coverage

Prove with a source containing many large event objects that:

- the reader performs bounded-size reads;
- early array elements are emitted/spooled before EOF and before all later elements are decoded;
- duplicate keys inside nested item/event payloads are rejected;
- alternate legal member ordering is accepted;
- malformed late input cleans the workspace.

No database creation or mutation belongs in this task.

## Constraints

No new dependency, portable format change, Pydantic contract change, import publication change, or CLI behavior change.

## Focused verification

Use the manifest-declared 0052 check only.
