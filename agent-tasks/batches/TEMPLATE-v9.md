# Batch: <batch-id>

Full local required: `false`

## Objective

<what must be achieved>

## Scope

<allowed code/product scope>

## Work

1. <work item>
   - <requirements>
   - Focused checks:
     ```bash
     <commands>
     ```

2. <work item>
   - <requirements>
   - Focused checks:
     ```bash
     <commands>
     ```

## Final verification

```bash
<final focused/integration commands>
make compile
git diff --check
```

## Non-goals / stop conditions

- <explicit exclusions>

## Handoff

Implementer stops at:

`READY FOR REVIEW`

Reviewer is an independent role. Review the exact implementation head without
reading the implementer's self-review, handoff, conclusions or remaining-risk list.
The reviewer may append correction commits to the same PR/branch only for
independently established findings, according to `agent-tasks/common/v9.md`.

Neither implementer nor reviewer merges.
