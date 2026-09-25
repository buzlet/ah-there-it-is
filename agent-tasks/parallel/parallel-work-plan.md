# Parallel work while 0061-0070 is in progress

Status: temporary planning material only. Do not merge into main until batch 0061-0070 is complete and reconciled.

Base main: `fea00581b6f826534cb60d440d14f713da0d9849`.

## Finding

There are no remaining unresolved core-MVP product-semantic gates. The active quantity/lifecycle/Undo batch owns the remaining core implementation.

Parallel work must therefore avoid files or behavior owned by 0061-0070.

## Safe parallel work now

### 1. Provider/model evaluation subsystem design

Safe now as documentation/audit only.

Why it is useful:

- provider/model promotion is intentionally outside inventory-domain behavior;
- the repository already has scenario evaluation, live evaluation, model probes, prompt experiments, replay and evaluation logs;
- what is still missing is a single explicit promotion/benchmark contract tying those pieces together.

Do not implement it while 0068 is changing prompt/scenario/evaluation behavior.

Deliverable: `agent-tasks/parallel/provider-evaluation-gap-audit.md`.

### 2. Photo/media-reference contract design

Safe now because current batch explicitly excludes images/media.

Goal: define the narrow boundary between Item and a future external media service without choosing storage/vision implementation.

Deliverable: `agent-tasks/parallel/media-reference-contract-draft.md`.

### 3. Telegram bot adapter contract design

Safe now because current batch excludes Telegram and transport abstractions.

Goal: document a single-user bot adapter around the existing text application boundary without adding Telegram concepts to the inventory domain.

Deliverable: `agent-tasks/parallel/telegram-bot-adapter-draft.md`.

### 4. Process executor-boundary hardening

Technically independent of inventory application code and likely low-conflict with 0061-0070.

Candidate scope:

- make lifecycle/preflight tooling validate declared execution channel/user/workdir more mechanically;
- reduce reliance on prose-only launcher checks;
- keep unique-checkout rules explicit;
- add process-tool-only tests.

However, this is **not safe to execute concurrently on the same Remote Commander working tree**. A second code executor requires a separate checkout/device. Merely creating a second Git branch is insufficient because branch checkout mutates shared worktree state.

Prepare a later task spec if a separate execution checkout becomes available.

## Work that should wait for 0061-0070

### Final correctness audit

Wait. The active batch changes the schema, InventoryService, agent tools, web schemas/routes, portable format, evaluation scenarios and runtime integration. Auditing those surfaces now would be immediately stale.

### Empty Conversation on failed first turn

Wait. It touches AgentRunner/conversation/idempotency transaction boundaries, which overlap heavily with 0067 and 0069.

### Evaluation implementation

Wait. 0068 intentionally changes Russian prompt/scenario/evaluation behavior. Designing the benchmark contract is safe; changing its implementation is not.

### Portable/storage follow-up

Wait. 0066 and 0070 own portable-v3 and recovery/runtime compatibility.

### Web/manual UI refinement

Wait. 0065 and 0070 own those surfaces.

## Stale backlog reconciliation

`agent-tasks/designs/post-0050-engineering-backlog.md` is no longer a reliable live backlog:

- its Priority A items were implemented by 0051-0060;
- multi-user/concurrency items are no longer core scope;
- Windows storage publication remains conditional;
- Empty Conversation remains a possible correctness follow-up;
- executor-boundary hardening remains useful process work.

Do not edit the main backlog while 0061-0070 is active. Reconcile it after that batch lands so the post-batch audit can use the final runtime truth.

## Proposed order after 0061-0070

1. reconcile this parallel branch against the merged 0061-0070 main;
2. final correctness audit of the complete core;
3. fix only concrete audit findings;
4. formalize provider/model promotion benchmark;
5. declare core MVP complete;
6. optional Telegram/photos work afterwards.
