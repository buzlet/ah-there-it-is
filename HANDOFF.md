# Session handoff

## Current state

Repository: `buzlet/ah-there-it-is`.

Product stages through Stage 26 and implementation/review work through 0090 are complete on main.

Media/Telegram 0071–0080 and model-evaluation 0081–0083 are merged. Their independent review corrections are also merged: PR #84 for media/Telegram and PR #83 for model-evaluation hardening.

Final code-level MVP hardening 0084–0090 was implemented by PR #87. Independent review corrections were integrated by PR #88 and then carried into PR #87 before its merge. Final post-merge application CI on main was green.

Batch 0061–0070 merged as PR #77 at `33710743ba1d3c7a380cf4a2a37457fb94e89eaa`; its exact PR head was `35ee225e9a9159457a395d0f03bed37c5c6777af`. Authoritative CI was green.

Active implementation protocol for newly issued work:

`agent-tasks/common/v9.md`

Execution environment is selected separately through one profile under
`agent-tasks/executors/`; task files do not embed the executor selection.

v8 remains historical authority for work issued under it. No active batch remains
in the v8 lifecycle at v9 adoption.

Historical process material is archived and is not normal implementation context.

## Execution

v9 separates task definition from execution environment.

For implementation, the orchestrator hands the agent two separate paths: the task
and one executor profile, both read at the issuance SHA. Independent reviewer
handoff additionally freezes and supplies the exact implementation head `I`.

Executor profiles:

- `agent-tasks/executors/chatgpt-sandbox.md`
- `agent-tasks/executors/u24-direct-shell.md`
- `agent-tasks/executors/u24-remote-commander.md`
- `agent-tasks/executors/windows-git-bash.md`

The executor file owns workdir/user/bootstrap/network/publication rules. The task
file contains none of them. Python 3.12 application CI remains authoritative.

## Verification model

For new v9 work:

- one batch file in `main`;
- its commit is the issuance SHA;
- one pre-created implementation branch from that SHA;
- ordinary task commits as recovery checkpoints;
- one PR and authoritative exact-head CI;
- independent reviewer receives the exact implementation head but does not read the implementer's self-review, handoff, conclusions or remaining-risk list;
- reviewer may append correction commits to the same branch only from independently established findings;
- implementer/reviewer never merge;
- orchestrator owns current-main compatibility, merge and post-merge verification.

No control branch, seed, assignment copies, lifecycle journal, committed self-review
record or separate correction PR is part of the normal v9 path.

## Useful process tools

- `tools/agent/canonical_verifier.py` when a batch explicitly requires full-local verification;
- `tools/agent/ci_waiter.py` where supported;
- lifecycle checkpoint tooling remains legacy for v8/historical batches.

## Product summary

Current system includes nested inventory trees, deterministic search, explicit location truth, exact/approximate/unknown quantity, generic removed/restore lifecycle, equivalent-lot splits, immediate one-level compensating Undo, historical Event evidence, provider-neutral scenarios, write-target safety, atomic turns/receipts, crash-safe idempotency, bounded conversation context, doctor/FTS repair, hardened backup/restore/rehearsal, projection/streaming portable-v3 export with frozen v1/v2 import compatibility, snapshot-consistent export, bounded/streaming/race-safe portable import, bounded physical/doctor diagnostics, ordered Item photo references without image bytes, and a single-user/private-text Telegram long-poll adapter with durable conversation mapping, request replay and checkpoints.

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

Code-level MVP acceptance/hardening through 0090 is complete.

Next is a Direct-shell deployment-readiness batch 0091+ on the actual target server. It owns host preparation: service manager, environment/secrets placement, filesystem layout, deployment/restart rehearsal, operational paths and other server-specific setup.

The known Direct follow-up is to guarantee exactly one Telegram long-polling process for the production bot/database, including restart/upgrade overlap and crash timing around committed mutation versus reply/checkpoint.

Only after Direct deployment readiness is green should the project be declared MVP-ready.
