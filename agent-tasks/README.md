# Orchestrated implementation tasks

This directory is the durable archive of implementation-agent assignments.

## Layout

- `common/vN.md` contains a versioned reusable execution protocol.
- `assignments/NNNN-*.md` contains one concrete assignment.
- `reviews/NNNN-rN.md` records orchestrator review results and correction rounds for that assignment.
- Assignment numbers are monotonic and are never reused.
- Once a common protocol version has been referenced by an issued assignment, that protocol file is immutable; create `vN+1` for future changes.
- Issued assignment and review files are historical records: do not rewrite old instructions/results to make them look better after the fact.
- If review requires a correction to the same PR, record another review round. If it requires materially new scope, create another numbered assignment and reference the earlier assignment/PR.

The purpose is to preserve the exact instructions that produced each implementation so prompt quality can be reviewed later.

## Handoff model

The orchestrator owns task definition and verification. The implementation agent owns only the implementation interval between those two handoffs.

The orchestrator guarantees that no other repository work occurs between publishing an assignment and the implementation agent starting it. After the agent opens its PR, it stops repository work until the orchestrator reviews the PR and either accepts it or issues another instruction.
