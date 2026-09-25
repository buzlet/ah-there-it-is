# Session handoff

## Current state

Repository: `buzlet/ah-there-it-is`.

Product stages through Stage 26 and assignments through 0060 are complete.

Batch 0051–0060 merged as PR #71 at `c07f5a95f844f10f58f13b44e8e43978d966803a`; its exact PR head was `6518c0761cfe1a2d738a6aa95cec9ad843f67d88`.

Active implementation protocol:

`agent-tasks/common/v8.md`

Historical process material is archived and is not normal implementation context.

## Execution

Direct U24 execution runs as OS user `rdu01`.

Each issued patch/batch receives its own exact checkout path under:

`/home/rdu01/projects/<patch-name>`

The agent must stay inside that checkout for Git, edits, Python, Just and tests. Do not switch to `gpt`, do not use sudo, and do not reuse another patch checkout.

The direct-shell environment is already connected to U24.

Remote Commander on U24 remains available when explicitly selected.

Python 3.12 is the only required CI/test compatibility target. Do not add Python 3.13+ verification lanes without an explicit future decision.

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

Current system includes nested inventory trees, deterministic search, explicit location truth, sold/discarded lifecycle + reactivation, historical Event path evidence, provider-neutral scenarios, write-target safety, atomic turns/receipts, crash-safe idempotency, bounded conversation context, doctor/FTS repair, hardened backup/restore/rehearsal, projection/streaming portable-v2 export, snapshot-consistent export, bounded/streaming/race-safe portable import and bounded physical/doctor diagnostics.

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

The next step is implementation planning/batching, not further quantity product-semantic design.

## Product/deployment scope

Accepted scope is recorded in:

`agent-tasks/designs/product-scope-decisions.md`

Important decisions:

- application is single-user;
- web/Telegram/other external surfaces may use different source identity labels, but no first-class Channel or multi-user domain model is required;
- backup scheduling/retention/off-machine copying is external infrastructure;
- traces are retained for future replay/evaluation/model improvement; purge/retention management is external;
- voice-to-text is external and the application receives text;
- future photo support may associate one-or-many external media references with an Item;
- QR/barcodes are not implemented;
- Telegram bot is the only currently desired external chat transport; its single-account security/binding lives in Telegram adapter infrastructure;
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

## Remaining product decisions

None required for core MVP.

Further semantic changes require a new explicit decision. The next work is implementation planning/batching.
