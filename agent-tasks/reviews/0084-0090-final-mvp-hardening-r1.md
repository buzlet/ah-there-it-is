# 0084–0090 final MVP hardening — self-review r1

Status: **MVP candidate ready for independent review**

## Provenance

- Repository: `buzlet/ah-there-it-is`
- Immutable control SHA: `898e2dd7cf99e691a8cc8dc7de4bcf9e936585d7`
- Expected/start main: `805d183c2e59efcde9b306ff27171cb96d5dab44`
- Implementation branch: `feat/final-mvp-hardening-0084-0090`
- Authoritative remote seed: `6a9a7b803cfbe6c41060cc6b7916138163c925c5`
- Seed parent: `805d183c2e59efcde9b306ff27171cb96d5dab44`
- Source artifact: `sandbox-bundle-805d183c2e59efcde9b306ff27171cb96d5dab44` (artifact `10881201617`)
- `full_local_required: false`; repository-wide local `make check` was intentionally not run.

The remote seed contains the active manifest and byte-identical assignment copies for 0084–0090. Control/source blob SHA equality was checked when the seed was created.

## 0084 — integrated chat transaction and cross-surface invariants

Remote checkpoint: `fbdc21b052f3e5f56b0e9dfccd46f2b2fbf54898`

Correction count: **0 production corrections**.

Rechecked Web/Agent/Telegram convergence on `ChatApplicationService`, request-key replay, backend-owned mutation receipts, write-target safety, source identity as audit metadata only, and failure atomicity.

The suspected failed-first-turn case was reproduced before changing code. Persisted state is intentional and contract-consistent:

- one `Conversation` survives as the audit/FK anchor for the failed run;
- no `Message` rows survive;
- one failed `AgentRunLog` survives and references the `Conversation`;
- one failed keyed `ChatRequestRecord` survives, with no successful run/conversation binding and no mutation receipts.

The conversation row is required to preserve failed-run evidence and is not a second mutation pipeline. Added focused regression coverage for this exact state instead of deleting audit history.

Declared 0084 focused pytest set, `make compile`, and `git diff --check`: green.

## 0085 — crash, idempotency and recovery hardening

Remote checkpoint: `b721a0616580c86b63cfb13b7d7220a7095d7ef4`

Correction count: **0 production corrections**.

Added fault-injection coverage for process death after keyed reservation and after provisional AgentRunner work before final commit. Verified:

- a reservation can durably remain `processing` without business mutation after process death;
- no TTL/automatic retry is required or introduced;
- explicit operator recovery uses a distinct request key and leaves the original processing record observable;
- provisional mutation work rolls back when the enclosing turn does not durably commit;
- completed/failed/processing replay behavior remains fail-closed;
- Telegram replay prevents duplicate mutation across send/checkpoint uncertainty.

Declared 0085 focused pytest set, `make compile`, and `git diff --check`: green.

## 0086 — lifecycle, Undo, media and quantity integration

Remote checkpoint: `25903ff2031281378f6d92525fef674719480848`

Correction count: **0 production corrections**.

Added adversarial combined-operation coverage, including media plus lifecycle/quantity mutation in one turn and immediate multi-receipt Undo. Rechecked that compensation is atomic, stale state fails closed, split children do not inherit media, split Undo does not merge Items, detached media metadata can be restored without deleting external bytes, and zero quantity does not imply removal.

Declared 0086 focused pytest set, `make compile`, and `git diff --check`: green.

## 0087 — security, privacy and malformed boundaries

Remote checkpoint: `4c7281ab4ed850e3a31dd5dac1693b9341baec38`

Correction count: **2 reproduced defect classes, both corrected narrowly**.

### Finding 1 — boolean aliases accepted by integer boundaries

Pydantic integer fields accepted Python/JSON booleans because `bool` is an `int` subtype/coercible value. This could alias `true` to ID/quantity/position `1` at Web and Agent tool boundaries.

Regression tests first reproduced the defect against an existing Item and Web JSON payloads. The correction replaces boundary integer fields with strict annotated integer types while retaining their existing range constraints. No domain/product semantics changed.

### Finding 2 — provider exception details could persist configured secrets

Provider HTTP/request errors could contain values echoed from configured API keys, credential-bearing/query-bearing base URLs, or nested provider request extras. Those exception strings can become durable failed-run/request evidence.

A synthetic-secret regression reproduced the persistence path. The correction derives request-only sensitive values from provider configuration and redacts them from provider exception details before raising `ProviderRequestError`. Trace base-URL sanitization remains intact; normal provider responses/tool traces are unchanged.

Declared 0087 focused pytest set, `make compile`, and `git diff --check`: green.

## 0088 — boundedness, scale and concurrency audit

Remote checkpoint: `53920c184dfd7ca3826882b76dc4032e001ef8b9`

Correction count: **0 production corrections**.

Added deterministic structural coverage for a 250-message conversation. Agent context and user-facing history reads remain explicitly limited and require bounded SQL containing `LIMIT`; statement counts remain bounded. Existing scale/media/storage/idempotency/Telegram focused coverage was rechecked without wall-clock thresholds.

No caching, queue, worker, lease, or benchmark-by-time subsystem was introduced.

Declared 0088 focused pytest set, `make compile`, and `git diff --check`: green.

## 0089 — package, startup, schema and runtime semantics

Remote checkpoint: `46911bbd54fba72c00f95b2605fdeeb6d23ac17c`

Correction count: **0**; checkpoint is intentionally tree-identical to 0088.

Rechecked wheel package data/migrations, migration head/fresh/upgrade behavior, Web and Telegram read-only schema gates, no startup auto-migration, doctor semantics, runtime CLI construction/import behavior, secret-safe configuration paths, and offline sandbox packaging/bootstrap semantics.

Declared 0089 focused pytest set, `make migration-check`, `make compile`, and `git diff --check`: green.

No deployment-host configuration was created.

## 0090 — cumulative final integration review

Cumulative `seed..HEAD` review found no new product scope. In particular, this batch did not introduce Item merge, multi-user/channel/role abstractions, Telegram groups/webhooks/photo ingestion, image bytes/vision, QR/barcodes, built-in voice, multilingual/fuzzy/embedding search, generic hard delete, external media storage, deployment infrastructure, or a new dependency.

Web, Agent and Telegram continue to share the same mutation/idempotency boundary. Quantity/lifecycle/Undo/media invariants remain coherent. Evaluation hard gates remain fail-closed.

### Final focused integration

- Group A — mutation/chat/Telegram: **green** as the exact declared pytest group.
- Group B — persistence/package/boundedness: the exact single-process command exceeded the sandbox execution-call ceiling before completion on repeated attempts. The **same complete declared test-file union** was then executed deterministically in bounded shards (all 9 `test_target_scale.py` tests as explicit node IDs plus each of the remaining 9 declared files); every shard was **green**. No test was omitted or substituted. Exact-head Python 3.12 application CI remains the authoritative repository-wide proof.
- Group C — evaluation subsystem: **green** as the exact declared pytest group.
- `make provider-contract`: **green** (23 passed).
- `make migration-check`: **green**.
- `make corpus-check`: **green** (71/71 corpus cases).
- `make scenario-check`: **green** (71/71 scenarios).
- `make scenario-eval`: **green** (71 completed, 0 failed; 71 checks passed, 0 failed).
- `make retrieval-eval`: **green** (86 passed, 0 failed; starvation diagnostic passed).
- `make compile`: **green**.
- `git diff --check`: **green**.

## DIRECT FOLLOW-UP

`DIRECT FOLLOW-UP: Guarantee exactly one Telegram long-polling service instance for the production database/bot token, including restart and upgrade overlap. On the real deployment host, intentionally attempt to start a second poller and verify the service-manager/runtime arrangement rejects or terminates it before both instances can poll/send; also verify restart cannot overlap old and new pollers. Application request-key idempotency prevents duplicate inventory mutation, but a send-succeeded/checkpoint-uncertain replay can legitimately duplicate the external reply, so this is a target-host singleton requirement rather than a speculative distributed lease.`

## Remaining risks

- The sandbox uses Python 3.13; authoritative exact-head `application-ci` on Python 3.12 is still required after the PR is opened.
- Telegram send/checkpoint uncertainty can duplicate an outbound reply while preserving mutation idempotency; the production singleton requirement above limits accidental concurrent pollers but cannot make Telegram send acknowledgement transactional with the local polling checkpoint.
- A failed first turn intentionally retains an otherwise empty `Conversation` as an audit/FK anchor. Regression coverage now fixes this persisted-state contract; changing its user-visibility/product semantics would be a separate product decision, not hardening.

No production/deployment readiness claim is made by this review.
