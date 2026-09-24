# Assignment 0059: integrated-batch manifest and preflight support

## Objective

Align `tools/agent/lifecycle_checkpoints.py` with the actual active v8 integrated-batch manifest.

The current parser expects the older per-task `### task` blocks with a distinct Branch/Spec source/Assignment destination per task. Current v8 batches instead have one implementation branch, an ordered task list, one exact-spec list and one seed-destination list.

## Required behavior

- Add explicit parsing support for the current v8 integrated-batch manifest shape.
- Parse and validate at minimum:
  - Batch ID;
  - expected start-main SHA;
  - implementation branch;
  - execution user/workdir where present;
  - review destination;
  - `full_local_required`;
  - ordered task IDs/titles;
  - exact task spec paths;
  - seed assignment destinations.
- Require one-to-one task/spec/destination cardinality and identical task-ID order.
- Reject:
  - duplicate/missing task IDs;
  - spec/destination ID mismatch;
  - unsafe repository-relative paths;
  - malformed start SHA;
  - missing implementation branch;
  - contradictory task ordering.
- Do not require a unique branch per task for integrated batches.
- Preserve support for historical legacy manifests if inexpensive; archived legacy material must not dictate current v8 behavior.
- Update preflight so one current v8 batch can be checked against:
  - exact immutable control SHA/ref;
  - exact start-main;
  - clean expected checkout;
  - one expected implementation branch;
  - the selected task's exact spec source/destination;
  - the complete ordered task set.
- Preflight remains read-only.
- Expose the detected manifest format/mode in machine-readable output so callers cannot confuse legacy and integrated semantics.
- Update `tools/agent/README.md` only as necessary to describe the active integrated-batch mode.

## Tests

Add deterministic fake-Git tests covering a current 10-task integrated manifest, malformed list alignment, wrong control/start SHA, dirty checkout, and legacy parser compatibility.

Do not make tests depend on active task files that will later be archived; use dedicated fixtures/generated manifest text.

## Constraints

Process tooling only. No application/runtime behavior, network calls, workflow changes or dependencies.

## Focused verification

Use the manifest-declared 0059 check only.
