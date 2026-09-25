# Batch review: media + Telegram core 0071–0080

Date: 2026-09-25
Implementation branch: `feat/core-media-telegram-0071-0080`
Seed: `401ddf6de8633ac68b226509130bb8ddca1252f5`
Reviewed head before PR: `50ae030`

## Scope audit

- `ItemMedia` stores only provider/reference/caption/order metadata; no image
  bytes, thumbnails, vision inference or image-to-fact path was added.
- Attach, reorder, detach, remove/restore and split behavior preserve stable
  IDs and the source-only media invariant. Immediate media Undo uses
  compensating association mutations and never calls an external delete.
- Web media endpoints and the agent photo tools use stable Item/media IDs and
  the existing write-target/receipt/history boundaries.
- Web and Telegram call `ChatApplicationService`, which delegates to the
  existing request-key/AgentRunner path. Telegram derives exactly
  `telegram:<update_id>` and persists a private-chat mapping plus next offset.
- The adapter rejects unauthorized users, non-private chats and non-text
  updates before application invocation. Send/checkpoint uncertainty can
  resend a reply, but request-key replay prevents a second inventory effect.
- Bot token values stay out of source identity, request keys, traces, events,
  receipts and error text. Transport tests use fake/httpx transports only.
- No Telegram webhook/group/photo ingestion, generic User/Channel/Role model,
  portable-v4 change, provider/model campaign implementation, or new runtime
  dependency was introduced.

## Runtime/docs

- `ah-there-it-is telegram-bot` is explicit and performs the same read-only
  schema gate as Web before constructing DB/LLM/chat/Telegram services.
- Telegram settings remain optional for Web/imports; missing bot settings fail
  only the bot command without echoing the secret token.
- `.env.example`, README, module map and HANDOFF document the implemented API,
  startup/configuration and unsupported boundaries.

## Verification evidence

- Every task 0071–0080 has a focused check, `make compile`, diff check and
  checkpoint commit.
- Final focused integration and provider-contract checks passed before this
  review; cumulative `seed..HEAD` diff check is clean.
- Full local v8 sequence was run once after this review. Its first `make check`
  exposed a versioned-prompt drift introduced by the photo safety prompt; the
  only narrow correction synced `prompts/inventory-v1.txt`, after which the
  focused prompt test (2 passed), compile and diff check were green. The
  remaining gate steps (migration, corpus, scenario and retrieval) were green
  in that same sequence; the full gate was intentionally not rerun.
