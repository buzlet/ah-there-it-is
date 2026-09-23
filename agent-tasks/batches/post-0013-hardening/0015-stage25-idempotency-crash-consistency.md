# Assignment 0015: Stage 25 idempotency crash consistency

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/stage25-idempotency-crash-consistency`

## Objective

Close the crash window between committed business changes and `ChatRequestRecord` completion for keyed chat requests, using the receipts/turn semantics delivered by Assignment 0014.

## Required behavior

- Keep request-key reservation as a durable pre-execution step before model work.
- For a newly reserved keyed request, make these part of **one final transaction/commit**:
  - business/domain changes;
  - successful conversation messages;
  - completed `AgentRunLog`;
  - committed mutation receipts;
  - `ChatRequestRecord.status = completed`;
  - `ChatRequestRecord.agent_run_id`.
- The keyed-flow coordinator, not `AgentRunner` independently, must own that final commit. Preserve a simple committed-by-runner path for unkeyed execution if useful.
- Failure before the final commit must roll back business/run/message changes, then mark the reservation failed in a separate durable transaction.
- Treat an exception/uncertain result from the final commit specially: do **not** immediately mark the request failed. Re-open durable state through a fresh connection/session and reconcile:
  - if the request is durably completed and points to a valid completed run, return/replay that committed result;
  - if it is still durably processing and the business transaction did not commit, mark it failed with an explicit commit-failure reason;
  - if durable state is internally inconsistent, leave evidence intact and surface an idempotency error rather than guessing.
- A failure after successful commit but before HTTP response must be safely replayable with the same request key and must not create another mutation/Event/receipt.
- Preserve existing conflict behavior for reuse of a key with different request content and the explicit recovery model for genuinely failed requests.
- Completed replay must include the authoritative `changes_applied`/receipts introduced by 0014.

## Fault-injection/concurrency coverage

At minimum:

- failure immediately before final commit;
- successful commit followed by simulated response loss, then same-key replay;
- commit call that raises after durable commit, reconciled as completed through a fresh session;
- commit failure with durable state still processing, reconciled then marked failed without business changes;
- concurrent attempts using the same key cannot execute two business mutations;
- different-content reuse remains conflict;
- failed recovery semantics remain explicit and linked.

Also perform one deterministic local two-connection probe that pauses a model turn after its first flushed write and observes whether a second SQLite writer is blocked. Record the observed behavior in the review record only; do not redesign transaction architecture solely from this probe.

## Constraints

No new retry automation for failed/processing requests, no time-based expiry, no distributed lock/service, no async ORM, no Location lifecycle/history work, provider tuning, dependency/runtime/workflow upgrades or unrelated refactoring.

## Focused verification

Run focused chat-request/runner/fault-injection/concurrency tests plus the local lock probe, then the canonical v4 verification set.
