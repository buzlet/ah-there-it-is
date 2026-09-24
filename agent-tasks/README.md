# Orchestrated implementation tasks

This directory has an **active layer** and a **historical archive**.

## What an implementation agent reads by default

Read only:

1. root `AGENTS.md`;
2. the exact issued assignment or immutable batch manifest;
3. `agent-tasks/common/v7.md`;
4. source/tests directly needed by the assignment.

Do not recursively scan this directory.

## Active layout

- `common/v7.md` — current implementation+verification protocol.
- `assignments/` — only current/not-yet-archived issued assignments.
- `reviews/` — current/not-yet-archived review records.
- `batches/` — current/not-yet-archived batch control/status files.
- `designs/` — unresolved/current product or architecture decisions.

## Archive

`archive/` contains completed/superseded history:

- old protocol generations;
- completed assignments;
- completed reviews;
- completed batch manifests/results;
- resolved design documents;
- full historical snapshots of previously oversized root status docs.

Archive files are retained as evidence. They are **not current instructions**.

Open them only when an assignment explicitly needs historical evidence or when diagnosing a regression/decision.

## Archiving rule

After a batch/stage is accepted and no active task needs its files as mutable current context, orchestration may move the completed assignment/review/batch documentation into `archive/` without rewriting Git history.

The implementation agent does not archive its own active assignment before merge.

## Current protocol

`agent-tasks/common/v7.md`
