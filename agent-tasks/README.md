# Orchestrated implementation tasks

This directory is the durable archive of implementation-agent assignments.

## Layout

- `common/vN.md` contains a versioned reusable execution protocol.
- `assignments/NNNN-*.md` contains one concrete assignment.
- `reviews/NNNN-rN.md` records verification/review results and correction rounds for that assignment; under protocol v3 the implementation+verification agent writes this record itself.
- Assignment numbers are monotonic and are never reused.
- Once a common protocol version has been referenced by an issued assignment, that protocol file is immutable; create `vN+1` for future changes.
- Issued assignment and review files are historical records: do not rewrite old instructions/results to make them look better after the fact.
- If review requires a correction to the same PR, record another review round. If it requires materially new scope, create another numbered assignment and reference the earlier assignment/PR.

The purpose is to preserve the exact instructions that produced each implementation so prompt quality can be reviewed later.

## Handoff model

The orchestrator owns product/architecture direction, stage selection, assignment design, and decisions on genuine blockers. Under current protocol v3, one trusted implementation+verification agent owns the complete routine assignment lifecycle: implementation, self-review, local verification, PR/CI correction loops, merge, main synchronization, review record, and compact reporting.

The orchestrator guarantees that no other repository work occurs between publishing an assignment and the agent starting it. The agent stops only after the assignment is merged and `main` is synchronized, or earlier when a real architecture/product/infrastructure blocker requires an orchestrator decision.

Assignments using older protocols remain historical evidence of the workflow that was in effect when they were issued. A superseded-before-execution assignment is recorded with an `r0` review rather than rewritten.
