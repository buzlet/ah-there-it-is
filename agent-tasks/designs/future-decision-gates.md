# Future decision gates

Only unresolved/current gates are kept here. Completed gates and their full historical rationale are archived under `agent-tasks/archive/designs/`.

## Gate C — quantity and identical physical instances

This is the next required product-semantic pause.

Question: what does one Item represent when there are multiple physically identical units?

Examples:

- five identical batteries in one box;
- two identical chargers in different Locations;
- moving only two units from a quantity of five;
- same model but distinct serial numbers or condition.

Current recommended direction, not yet implementation authority:

- individually distinguishable object → separate Item;
- truly fungible co-located units → one Item with quantity;
- partial move/sale/disposal → explicit split into a new stable Item/group with provenance;
- split/merge must define history, aliases/attributes copying and portable semantics.

Do not implement partial-quantity mutation before this is decided.

## Gate D — correction / undo / destructive removal

### Correction / undo

Preferred domain principle:

- do not rewrite prior Events;
- corrections create compensating mutations/Events;
- one-click undo, if added, should be operation-specific and append-only.

A product decision is still needed before generic Undo UX.

### Hard delete / archive

Current default remains no ordinary hard delete.

Terminal sold/discarded state plus filtering preserves useful memory. A future destructive purge would need an explicit privacy/product contract and documented history consequences.

## Gate E — retention and operational backups

### Agent trace retention

Run logs intentionally contain prompts, bounded conversation input, tool traces/results and outputs.

Before long-term real-data use at scale, decide:

- indefinite retention;
- manual purge;
- time-based raw-trace retention;
- whether aggregate evaluation metadata survives raw trace deletion.

Do not add silent auto-deletion before this policy is chosen.

### Automated backup retention

Backup/restore primitives exist; scheduling does not.

Future decision points:

- schedule;
- retention count/age;
- local vs remote destination;
- encryption for off-machine copies.

Local rotating backups remain the default direction.

## Gate F — remote access / multiple users

The current product is single-user/local-first.

Before normal LAN/Internet exposure decide authentication/network boundary.

Before multi-user/household support decide:

- Item ownership;
- shared/private Locations;
- who has an `in_use` Item;
- Event actor attribution;
- permissions and search visibility.

Do not bolt user IDs onto the current schema without this model.

## Gate G — input modalities and external integrations

Optional later gates:

- voice: transcription location/privacy and mutation confirmation;
- images: file/blob storage, thumbnails, privacy and evidence semantics;
- QR/barcodes: stable-ID label lifecycle and write authority;
- Telegram/other chat: account linking, external-message idempotency and authorization.

These are separate product stages after core inventory semantics stabilize.

## Gate H — provider/model promotion policy

Keep provider selection outside domain architecture.

Future real-model evaluation may define:

- acceptable clarification rate;
- cost/latency/privacy tradeoffs;
- prompt version promotion;
- structured confirmations for risky writes.

Deterministic backend safety remains the hard guarantee regardless of model.
