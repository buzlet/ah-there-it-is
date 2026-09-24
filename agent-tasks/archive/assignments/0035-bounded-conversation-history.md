# Assignment 0035: bounded conversation history

## Objective

Remove unbounded persisted conversation-history loading from the browser restore path while preserving chronological display, feedback annotations and retry-safe chat behavior.

No inventory/domain mutation semantics change.

## Service contract

Replace normal UI/API use of unbounded `ConversationService.list_messages()` with a bounded latest-first cursor window.

Add a typed result such as `ConversationMessageWindow` with:

- messages returned in chronological display order;
- requested limit;
- `has_older`;
- `next_before_id` (or equivalent stable older-page cursor).

Contract:

- default limit: 50;
- maximum limit: 100;
- initial request returns the newest messages;
- older request uses a stable message-ID cursor;
- SQL query is bounded by limit + one lookahead row;
- no offset-based drift when new messages are appended.

Do not keep an unbounded list method on a normal web/read path merely for compatibility.

## Run/feedback annotations

The current conversation endpoint loads every AgentRunLog for the conversation.

Replace that with a bounded lookup for only assistant message IDs present in the returned message window.

The lookup must:

- only fetch runs relevant to the current returned messages;
- load feedback needed by the response;
- preserve run/rating/comment behavior;
- not authorize or mutate anything.

## HTTP contract

Keep:

`GET /api/conversations/{conversation_id}`

Backward-compatible core fields `id` and `messages` remain.

Add bounded cursor parameters and response metadata, e.g.:

- `limit`;
- `before_id`;
- `has_older`;
- `next_before_id`.

Reject invalid limits/cursors with HTTP 400.

## Browser restore

Initial chat restore loads only the newest bounded window.

Add an explicit lightweight "Load older" path/control when older messages exist.

Loading older messages:

- prepends them without duplicating the current window;
- keeps chronological visual order;
- does not clear current conversation state;
- does not interfere with pending-request replay detection;
- does not cause duplicate feedback controls.

Do not preload all older messages automatically.

## Tests

Cover:

- empty conversation;
- below/default/exact/max/over-max limits;
- >1000 messages;
- stable latest-window semantics;
- older cursor progression without duplicates/gaps;
- new messages appended between older-page requests do not shift the cursor result;
- only returned assistant message IDs drive run lookup;
- feedback annotations remain correct;
- invalid cursor/limit;
- browser restore renders newest page and can load older history;
- query/ORM work remains structurally bounded.

## Constraints

No schema/index migration, no message deletion/retention policy, no LLM context-window change.

## Checkpoint

Run only the 0035 focused checks from the batch manifest, then commit the 0035 task checkpoint.
