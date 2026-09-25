# Batch manifest: final integrated MVP hardening 0084–0090

Batch ID: final-mvp-hardening-0084-0090-2026-09-25

Protocol: agent-tasks/common/v8.md

Expected start main:

805d183c2e59efcde9b306ff27171cb96d5dab44

Implementation branch:

feat/final-mvp-hardening-0084-0090

Execution:
- host_profile: chatgpt-sandbox
- execution_channel: sandbox
- execution_user: sandbox
- workdir: /mnt/data/final-mvp-hardening-0084-0090
- source_artifact: sandbox-bundle-805d183c2e59efcde9b306ff27171cb96d5dab44
- source_artifact_id: 10881201617

Batch review destination:

agent-tasks/reviews/0084-0090-final-mvp-hardening-r1.md

Full local regression:

full_local_required: false

## Objective

Perform one final integrated **code-level** MVP correctness/hardening pass after reviewed and corrected 0071–0083.

This batch is allowed to:
- reproduce suspected defects;
- add adversarial/regression tests;
- make narrow corrections supported by those tests;
- improve code-level correctness, safety and boundedness where a concrete defect is demonstrated.

This batch is not allowed to add new product scope.

## Ordered tasks

1. 0084 — integrated chat transaction and cross-surface invariants
2. 0085 — crash, idempotency and recovery hardening
3. 0086 — lifecycle, Undo, media and quantity integration hardening
4. 0087 — security, privacy and malformed-boundary hardening
5. 0088 — boundedness, scale and concurrency audit
6. 0089 — package, startup, schema and runtime semantics audit
7. 0090 — final integrated MVP candidate review

Exact task specs:
- agent-tasks/batches/final-mvp-hardening-0084-0090/0084-integrated-chat-transaction-invariants.md
- agent-tasks/batches/final-mvp-hardening-0084-0090/0085-crash-idempotency-recovery-hardening.md
- agent-tasks/batches/final-mvp-hardening-0084-0090/0086-lifecycle-undo-media-quantity-hardening.md
- agent-tasks/batches/final-mvp-hardening-0084-0090/0087-security-privacy-malformed-boundaries.md
- agent-tasks/batches/final-mvp-hardening-0084-0090/0088-boundedness-scale-concurrency-audit.md
- agent-tasks/batches/final-mvp-hardening-0084-0090/0089-package-startup-schema-runtime-audit.md
- agent-tasks/batches/final-mvp-hardening-0084-0090/0090-final-mvp-candidate-integration.md

Seed destinations:
- agent-tasks/assignments/0084-integrated-chat-transaction-invariants.md
- agent-tasks/assignments/0085-crash-idempotency-recovery-hardening.md
- agent-tasks/assignments/0086-lifecycle-undo-media-quantity-hardening.md
- agent-tasks/assignments/0087-security-privacy-malformed-boundaries.md
- agent-tasks/assignments/0088-boundedness-scale-concurrency-audit.md
- agent-tasks/assignments/0089-package-startup-schema-runtime-audit.md
- agent-tasks/assignments/0090-final-mvp-candidate-integration.md

The seed commit must contain this manifest at its active batch path plus byte-identical copies of all seven task specs at the assignment destinations.

## Evidence-first correction rule

For a suspected defect:

1. reproduce it on the issued baseline/current task head;
2. add a focused regression/adversarial test that fails for the defect;
3. make the narrowest correction;
4. make the regression green;
5. run only the task-declared focused checks;
6. checkpoint.

If a suspicion is not reproducible and existing behavior satisfies the accepted contract, do not rewrite it "for cleanliness".

## Deployment boundary

The sandbox is intentionally **not** the deployment host.

Do not prepare the production server or invent target-host configuration.

Anything requiring the real host must be recorded exactly as:

`DIRECT FOLLOW-UP: <requirement / reproduction / verification>`

Those follow-ups belong to the later Direct-shell 0091+ batch on the actual deployment server.

## Scope exclusions

No:
- new product features;
- Item merge;
- multi-user/household model;
- generic User/Channel/Role abstraction;
- Telegram groups/webhooks/photo ingestion;
- external media-storage implementation;
- image bytes/vision inference;
- QR/barcodes;
- built-in voice;
- multilingual/transliteration/fuzzy/embedding search;
- generic hard-delete/purge;
- backup scheduling/retention/off-machine infrastructure;
- systemd/service-manager or target-host environment configuration;
- new dependency without a demonstrated unavoidable blocker;
- Python compatibility-policy changes;
- executor/process redesign.

## Verification model

Each task:
- self-review;
- declared focused tests;
- `make compile`;
- `git diff --check`;
- one checkpoint commit.

No repository-wide regression between tasks.

0090 runs the three declared integration groups and Make gates.

`full_local_required: false` because the sandbox full suite may exceed a single execution-call limit. Exact-head application CI on Python 3.12 remains authoritative for the repository-wide suite.

## Final lifecycle

After 0090:

- cumulative seed..HEAD self-review;
- review report at the declared path;
- one PR;
- exact-head application CI green;
- seed ancestry proof;
- clean implementation branch state.

**Do not merge the PR.**

The terminal status is:

`READY FOR INDEPENDENT REVIEW`

A separate reviewer will reconstruct requirements independently and may create a correction PR. Only the orchestrator integrates/merges after that review.
