# Draft parallel lane: provider/model evaluation 0081-0083

Status: DRAFT ONLY. Batch 0061-0070 is merged; reconcile exact tests/start SHA before issuance.

Purpose: give a slower independent implementation agent useful work that does not block or overlap the faster 0071-0080 media/Telegram lane.

## Branching model

After 0061-0070 merges, both lanes start from the **same reconciled main SHA**.

Fast lane:
- tasks 0071-0080;
- branch name TBD, recommended `feat/core-media-telegram-0071-0080`;
- owns ItemMedia, shared chat service, Telegram adapter/runtime and core integration.

Slow lane:
- tasks 0081-0083;
- branch name TBD, recommended `feat/model-evaluation-0081-0083`;
- owns only provider/model benchmark campaign tooling and reports.

Neither lane depends on commits from the other.

## File ownership rule

0081-0083 must not modify:

- inventory domain/services;
- web routes/templates;
- Telegram/media modules;
- migrations;
- AGENTS.md;
- HANDOFF.md;
- active batch manifests/reviews owned by 0071-0080.

Prefer new evaluation-focused modules/tests and `eval/` report/schema material.

This keeps both branches merge-order independent.

## Ordered tasks

1. 0081 — benchmark campaign schema and repeated runner
2. 0082 — benchmark aggregation and baseline/candidate comparison
3. 0083 — promotion hard-gate report and evaluation integration

## Non-goals

- no provider auto-promotion;
- no runtime model change;
- no model-specific inventory workaround;
- no live-provider dependency in normal CI;
- no multilingual benchmark expansion;
- no changes to application business behavior.

## Merge order

Either lane may merge first.

After one lane merges, rebase/merge-main the other only if necessary under the project process. Because file ownership is intentionally disjoint, conflict risk should be low.

Final MVP correctness audit starts from main containing both lanes.
