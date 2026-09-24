# Assignment 0021: bounded agent conversation context

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/hardening-bounded-conversation-context`

## Objective

Prevent long-lived conversations from loading and sending an unbounded persisted message history to every model round while retaining the complete stored conversation.

## Required behavior

- Keep complete `Message` persistence unchanged. This assignment limits only the context assembled for a new agent run.
- Add a bounded ConversationService read specifically for agent context.
- Use a fixed initial policy:
  - at most 40 persisted messages before the new user message;
  - query newest rows with SQL `LIMIT`, then restore chronological order;
  - if the retained window begins with an assistant message, drop that leading assistant message so the persisted window starts on a user message;
  - system prompt and current user message are outside this 40-message cap.
- `AgentRunner` must use the bounded context read rather than unbounded `list_messages()`.
- `AgentRunLog.input_messages` must record exactly the system + bounded prior messages + current user content actually sent to the model.
- Existing browser/manual conversation-history views, exports or diagnostics that intentionally need full persisted history must keep their current semantics.
- Do not introduce summarization, hidden memory, token counting, provider-specific context sizing or deletion of old Messages.
- Failed-turn semantics from Assignment 0014 remain unchanged.

## Scale coverage

With a conversation containing >=1000 persisted Messages prove structurally that one agent run loads at most the configured 40 prior rows from the database and sends no older messages.

Cover:
- fewer than 40 messages;
- exactly/over the cap;
- leading assistant dropped after truncation;
- chronological order;
- new conversation;
- failed-turn exclusions remain correct;
- replay/run logging reflects the actual bounded input.

## Constraints

No schema migration, no summarization, no provider/prompt changes, no retention/deletion policy, no Activity/search/mutation semantics, no dependency/runtime/workflow upgrades.

## Focused verification

Run focused conversation/runner/replay/scale tests, then the canonical v4 verification set.
