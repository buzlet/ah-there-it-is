# Assignment 0014: Stage 24 atomic agent turn and committed receipts

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/stage24-atomic-turn-receipts`

## Objective

Make one agent turn semantically atomic after the first data-changing operation and expose backend-generated committed mutation receipts independently of assistant wording.

## Required behavior

- Implement a deterministic turn outcome state machine:
  - before the first successful data-changing operation, read-tool errors may be returned to the model for correction;
  - any mutation-tool error immediately fails the turn and rolls back its business changes;
  - after the first successful `changed=true` mutation, any later tool error immediately fails and rolls back the turn;
  - a later model round cannot repair/revive such a failed turn;
  - an empty final assistant response after a changed mutation fails and rolls back;
  - a successful no-op reports `changed=false` and does not count as a data-changing operation.
- Introduce typed backend mutation receipts. Persist committed receipts in a dedicated `AgentRunLog` field and return them in `AgentRunResult`.
- Expose authoritative response metadata through chat APIs: at minimum `changes_applied` plus committed receipts. Assistant text remains explanatory and must not be treated as proof of mutation.
- Receipt data must be compact and backend-owned: operation, entity type/ID, changed flag, relevant stable before/after IDs where meaningful, and Event IDs where produced. Do not duplicate descriptions, full Event payloads or original user text into receipts.
- Receipts created before commit are provisional. A rolled-back/failed turn must expose no committed receipts. Diagnostic trace may retain attempted tool results only if they cannot be mistaken for committed state.
- Ensure Item update/move and create operations have truthful no-op/change behavior. No-op update/move must not create a new Event or a receipt claiming a change.
- Failed turns must not silently become successful conversation context. Adopt this explicit policy: a failed agent turn is retained in failed `AgentRunLog` diagnostics but its user message is not committed into the normal conversation message stream. The failed run may therefore have `user_message_id = null`; its `input_messages`/trace retain diagnostic context.
- Idempotent replay of an already completed run must reproduce the authoritative receipts/changes metadata from persisted run data, not reconstruct it from arbitrary tool trace.

## Schema/data

A packaged Alembic migration is expected for the dedicated persisted receipts field. Existing run rows remain valid with an empty receipt list/default-compatible representation.

Do not repurpose domain `Event` as the receipt store.

## Adversarial coverage

At minimum:

- successful mutation then failing read tool => full rollback;
- successful mutation then failing mutation tool => full rollback;
- later “corrected” model call cannot revive a post-mutation failed turn;
- mutation tool error before any successful mutation => failed turn/no business change;
- read error before any mutation may be corrected;
- empty final response after mutation => rollback;
- no-op update and no-op move => `changed=false`, no new Event, no false receipt;
- failed turn absent from normal future conversation context but present in failed run diagnostics;
- successful response exposes committed receipts regardless of assistant wording;
- replay returns identical committed receipt metadata.

## Constraints

Do not yet refactor the request-key reservation/final commit into one crash-atomic keyed transaction; that is Assignment 0015. No search-resolution changes beyond merged 0013 behavior, provider tuning, Location lifecycle semantics, historical snapshot/Activity work, dependency/runtime/workflow upgrades or unrelated refactoring.

## Focused verification

Run focused runner/dispatcher/inventory/evaluation/chat-response/migration tests, then the canonical v4 verification set.
