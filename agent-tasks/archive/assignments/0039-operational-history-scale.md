# Assignment 0039: operational-history scale regression

## Objective

Add deterministic structural scale coverage for the operational/history tables hardened by 0035–0038.

This assignment primarily adds shared test fixture/support and regression tests. Fix only defects directly exposed by these tests and still within this batch's read-path scope.

## Fixture

Add a test-only efficient fixture capable of creating, without model/provider calls:

- at least 1,000 persisted conversation messages in one conversation;
- at least 1,000 AgentRunLog rows with representative feedback/config groups;
- at least 1,000 ExperimentRun rows with source feedback/reviews and representative traces;
- at least 1,000 ChatRequestRecord rows with recovery links.

Use bulk/direct test setup where useful. Do not route fixture creation through slow external/model workflows.

Keep fixture deterministic.

## Structural assertions

No timing thresholds.

Assert bounded behavior using:

- returned row/page sizes;
- stable cursor/page progression;
- SQL/query count where meaningful;
- Session identity-map/ORM materialization counts where meaningful;
- deterministic ordering;
- no duplicate/gap behavior;
- all-time summary correctness despite paged list UI.

At minimum prove:

1. conversation restore initially materializes at most the configured message window and bounded associated runs;
2. evaluation page loads one bounded run page and summaries do not materialize every AgentRunLog;
3. experiment page loads one bounded run page and summaries do not materialize full source-run ORM graphs;
4. chat-request page has bounded rows and no per-row recovery-source N+1;
5. HTML navigation exposes access to older records;
6. existing read paths do not mutate Events/inventory state.

## Browser integration

Add/extend app tests so the four affected UI surfaces show bounded current data and valid previous/next or load-older links/controls.

Do not add JavaScript/browser automation unless current test style requires it; server/template structural assertions are preferred.

## Final cleanup

Audit affected services/routes/templates for obsolete fixed `100`, `200`, or `10_000` list ceilings that are now bypassing the new page/projection contracts.

Do not broaden the audit into unrelated inventory catalog limits.

## Constraints

No timing benchmarks, schema migration, dependency addition, product semantics or retention policy.

## Checkpoint

Run only the 0039 focused checks, commit the checkpoint, then perform the batch final integration checks from the manifest.
