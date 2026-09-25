# Session handoff

## Current state

Repository: `buzlet/ah-there-it-is`.

Product stages through Stage 26 and assignments through 0070 are complete.

Batch 0061–0070 merged as PR #77 at `33710743ba1d3c7a380cf4a2a37457fb94e89eaa`; its exact PR head was `35ee225e9a9159457a395d0f03bed37c5c6777af`. Authoritative CI was green.

Active implementation protocol:

`agent-tasks/common/v8.md`

Historical process material is archived and is not normal implementation context.

## Execution

Direct U24 execution runs as OS user `rdu01`.

Each issued patch/batch receives its own exact checkout path under:

`/home/rdu01/projects/<patch-name>`

The agent must stay inside that checkout for Git, edits, Python, Make and tests. Do not switch to `gpt`, do not use sudo, and do not reuse another patch checkout.

The direct-shell environment is already connected to U24.

Remote Commander on U24 remains available when explicitly selected.

A third execution channel is the ChatGPT sandbox. It uses the exact
`sandbox-bundle-<start-main-sha>` CI artifact, works only under an issued
`/mnt/data/<patch-name>` directory, runs `make sandbox-bootstrap`, and does not
use shell network access. See `agent-tasks/common/sandbox-execution.md`.

Python 3.12 remains the authoritative CI/test compatibility target. Sandbox
execution currently uses its preinstalled Python 3.13 environment as an additional
implementation environment, not as a new required CI matrix lane.

## Verification model

One coherent issued batch:

- one implementation branch;
- focused checkpoint per task;
- no full repository suite between tasks;
- one final PR;
- one authoritative full CI;
- full local regression only when manifest sets `full_local_required: true`.

The integrated-batch lifecycle tooling now treats an absolute manifest workdir as execution-host metadata; actual checkout identity is verified through the explicit runtime checkout parameter rather than requiring CI to use the U24 absolute path.

## Useful process tools

- `tools/agent/lifecycle_checkpoints.py`;
- `tools/agent/canonical_verifier.py` for manifest-declared full-local runs;
- `tools/agent/ci_waiter.py`.

## Product summary

Current system includes nested inventory trees, deterministic search, explicit location truth, exact/approximate/unknown quantity, generic removed/restore lifecycle, equivalent-lot splits, immediate one-level compensating Undo, historical Event evidence, provider-neutral scenarios, write-target safety, atomic turns/receipts, crash-safe idempotency, bounded conversation context, doctor/FTS repair, hardened backup/restore/rehearsal, projection/streaming portable-v3 export with frozen v1/v2 import compatibility, snapshot-consistent export, bounded/streaming/race-safe portable import and bounded physical/doctor diagnostics.

## Quantity / physical-instance decision

The main direction is accepted and recorded in:

`agent-tasks/designs/quantity-physical-instance-decision.md`

Accepted and closed:

- Item is a homogeneous physical lot and may represent one object or interchangeable units;
- quantity precision is exact / approximate / unknown; zero is never stored;
- a single semantic quantity-change operation may change both value and precision and keeps original text plus explicit/context reason;
- approximate arithmetic is performed; inconsistent/nonpositive approximate remainders become unknown unless the user explicitly indicates all;
- quantity ambiguity normally does not block an otherwise safe operation;
- partial move/take/removal uses an internal atomic split; source/remainder keeps its stable ID and the child receives a new stable ID;
- split provenance uses structured Events only; no lineage table;
- equivalent duplicate lots are allowed while accidental creation remains guarded;
- merge is not implemented;
- the future generic terminal state is removed with textual reason stored on Item and Event, and removal requires user intent;
- removed Items keep their last meaningful quantity and may be restored under the same stable ID;
- split copies Item description/comment and the user may edit either copy;
- free-text comments may hold measurements such as cable meters without making them structured quantity truth;
- high-level tools express partial user intent directly and hide low-level split orchestration from the LLM;
- user-facing receipts/search presentation remain agent-driven rather than fixed;
- portable export advances to v3; frozen v1/v2 imports map legacy integer quantity to exact;
- existing sold/discarded Items migrate to removed while historical Events are preserved.

These quantity, lifecycle and immediate-Undo decisions are implemented runtime truth.

## Product/deployment scope

Accepted scope is recorded in:

`agent-tasks/designs/product-scope-decisions.md`

Important decisions:

- application is single-user;
- web/Telegram/other external surfaces may use different source identity labels, but no first-class Channel or multi-user domain model is required;
- backup scheduling/retention/off-machine copying is external infrastructure;
- traces are retained for future replay/evaluation/model improvement; purge/retention management is external;
- voice-to-text is external and the application receives text;
- Item photo support is required before MVP completion and associates one-or-many external media references with an Item while media bytes remain external;
- QR/barcodes are not implemented;
- a single-user Telegram text bot is required before MVP completion; its single-account security/binding lives in Telegram adapter infrastructure;
- provider/model comparison is a separate evaluation subsystem;
- Russian is the only supported natural language; Latin product/model identifiers remain ordinary data;
- no generic WhatsApp/transport abstraction is planned now.

## Correction / Undo and purge

Accepted and closed in:

`agent-tasks/designs/undo-correction-decision.md`

- ordinary corrections are compensating mutations/Events;
- one-level Undo is desirable only for the immediately preceding committed user mutation action;
- no redo or arbitrary older undo;
- compensation must be atomic and fail closed if current state no longer matches the expected post-state;
- partial-operation Undo does not merge lots; split children may remain separate after being moved/restored back;
- unsupported structural reversal may be reported rather than forcing deletion;
- no generic hard-delete/purge feature is implemented.

## Remaining work before MVP acceptance

No unresolved product-semantic gate blocks the next work.

Two implementation lanes are planned from the same post-0070 main:

- 0071–0080 media + Telegram;
- 0081–0083 provider/model evaluation campaign tooling.

They are designed to be merge-order independent. After both land, run one final
correctness audit and fix only concrete findings before MVP acceptance.
