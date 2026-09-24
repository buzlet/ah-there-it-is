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

The orchestrator owns product/architecture direction, stage selection, assignment design, and decisions on genuine blockers. Protocol v4 keeps one full implementation PR/CI cycle per stage and preserves the exact pre-implementation prompt as immutable Git history.

After accepting the previous agent's compact report, the orchestrator does not repeat routine implementation review, local tests, canonical checks, or CI verification. It works delta-first: read the previous review/current strategy, inspect only source areas needed to select the next gap, then create the next assignment.

For a normal v4 stage:

1. Synchronize `main` and create the assignment-named feature branch from it.
2. Create exactly one **seed commit** containing the issued assignment and any required `AGENTS.md` / `HANDOFF.md` / README strategy updates. Check only document/diff consistency; do not run application tests.
3. Push the seeded branch. Do **not** open a PR. Ordinary branch pushes intentionally do not run project CI.
4. Hand that exact branch to the implementation+verification agent. The agent records the initial branch head as `seed_sha` and must preserve it unchanged as an ancestor.
5. The agent adds implementation/test/review commits on the same branch, runs focused + canonical verification, marks only its own stage factually complete, opens the one implementation PR, owns the CI/fix loop, and merges using a merge commit.
6. The agent synchronizes clean `main` and returns the compact report. Only then does the orchestrator select and seed the following stage.

The seed commit may never be amended, rebased away, squashed, reset away, or force-pushed. The issued assignment and referenced common protocol are historical records and are not edited during implementation. The implementation agent may document that its assigned stage is complete, but it must not choose, describe, or create the next stage.

The orchestrator guarantees no concurrent repository work between seed publication and the agent's initial pull. Ordinary implementation failures are fixed autonomously by the agent; only genuine architecture/product/infrastructure blockers return to the orchestrator.

GitHub CI is PR-oriented under v4. Full application/scenario/provider-contract jobs run when a PR changes executable, test, schema, packaging, or workflow content. Pull requests changing only `AGENTS.md`, `HANDOFF.md`, `README.md`, or `agent-tasks/**` do not start those workflows at all. This avoids testing an unchanged application while retaining normal full verification for the implementation PR. The repository currently has no required-status-check branch protection; if required checks are introduced later, revisit this path filtering so a skipped workflow is never configured as mandatory.

### Minimal agent launcher

The chat handoff can stay short because v4 carries the standing rules:

```text
Work as the implementation+verification agent for buzlet/ah-there-it-is.
Use only Remote Commander on U24 (u24-gpt). Continue the already-seeded branch named by the assignment.
Read agent-tasks/common/v4.md and the assigned agent-tasks/assignments/NNNN-*.md, then own the complete v4 lifecycle through merge.
Return only the compact v4 final report.
```

Assignments using older protocols remain historical evidence of the workflow that was in effect when they were issued. A superseded-before-execution assignment is recorded with an `r0` review rather than rewritten.
