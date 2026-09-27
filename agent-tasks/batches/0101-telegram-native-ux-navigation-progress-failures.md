# Batch: 0101-telegram-native-ux-navigation-progress-failures

Full local required: `false`

## Objective

Implement the complete Telegram UX/transport cluster from issue #100 as one
coherent adapter change:

- compact deterministic inventory rendering;
- hierarchical location browsing and paging;
- callback-query navigation;
- native long-running draft progress;
- meaningful durable failure replies.

Keep this in one branch because callbacks, message editing, progress and failure
handling share the Telegram client/poller/adapter boundary.

## Product decisions

1. Telegram is a compact mobile inventory surface, not a verbose prose dump.
2. Inventory rendering is deterministic application behavior; do not ask the LLM
   to manufacture Telegram markup/navigation.
3. Navigation is read-only and uses stable database IDs.
4. One hierarchy level is shown at a time; do not recursively dump descendants.
5. Prefer editing one navigation message rather than flooding the chat.
6. Progress UI is advisory and can never affect inventory transaction semantics.
7. User-visible failure text is non-technical and must reflect authoritative
   durable state.
8. Preserve single-user authorization and request-key idempotency.
9. Do not implement a Telegram Mini App in this batch.

## Work 1 — deterministic compact renderer

Add a Telegram-specific renderer/view-model boundary that can render authoritative
structured inventory/location data without depending on free-form model prose.

Required behavior:

For a location contents query, show location context once:

```
Ванна

• зубная щётка
• туалетная бумага — ~5 рулонов

Места:
[inline child buttons]
```

Requirements:

- avoid repeated filler such as `хранится`, `находится`,
  `в инвентаре указано` when context is already established;
- approximate quantity renders with leading `~`;
- exact quantity has no `~`;
- unknown quantity invents no number;
- arbitrary Russian/Unicode inventory names are correctly escaped for the chosen
  Telegram parse mode;
- raw Markdown markers such as visible `**` never leak as pseudo-formatting;
- do not change the generic web/chat response contract merely to satisfy
  Telegram presentation if an adapter-specific view is sufficient.

## Work 2 — storage-location browser

Implement an explicit Telegram entry point for `Места хранения`.

Use a command/menu-compatible action such as `/locations` plus inline
navigation; if the existing bot command-registration mechanism can safely expose
it, wire it there. Do not require a Mini App.

Root view:

- show root locations only;
- use a bounded phone-friendly page size;
- buttons use stable location IDs, never display names as identity;
- optionally show compact counts when the meaning is unambiguous.

Drill-down:

- selecting a location shows its direct items and direct child locations;
- breadcrumbs such as `Ванна › Тумбочка`;
- `← Назад` goes to direct parent;
- root children provide `← Все места`;
- sibling/root lists page with Previous/Next controls;
- arbitrary hierarchy depth works;
- message edits are preferred over creating another navigation message.

Do not recursively render the full subtree.

## Work 3 — callback-query transport

Extend Telegram update/client models for callback queries.

Requirements:

- preserve authorization: callbacks are accepted only from the configured user
  and appropriate private chat/message context;
- answer callback queries promptly so Telegram does not leave a spinner;
- keep callback payloads compact and bounded by Telegram API limits;
- use stable IDs and explicit action/version prefixes;
- malformed/stale callbacks fail safely without mutation;
- navigation callbacks are read-only and must never enter inventory mutation
  idempotency paths;
- message edit failures are handled as transport/UX failures, not inventory
  writes;
- deterministic tests cover callback parsing, authorization, stale IDs,
  back/paging and Unicode display names.

Verify current Bot API request shapes against official Telegram Bot API
documentation while implementing; do not guess newer method parameters.

## Work 4 — native long-running progress

Replace typing-only progress as the preferred mechanism for requests that exceed
a short grace period.

Use Telegram `sendMessageDraft` when supported by the current Bot API.

Behavior:

- no visible draft for fast requests during roughly the first 2–3 seconds;
- one stable non-zero draft ID per in-flight request;
- same draft is updated rather than sending persistent status messages;
- no elapsed seconds in the user-visible text;
- neutral liveness cycles:
  - `Обрабатываю запрос.`
  - `Обрабатываю запрос..`
  - `Обрабатываю запрос...`
- update dots at a modest cadence around 3–4 seconds;
- after a substantially unchanged wait (roughly 20 seconds), occasionally show
  one of the fixed friendly phrases below;
- choose phrases in a shuffled/non-repeating order per request and exhaust all
  ten before repeating;
- rotate phrases slowly (roughly 15–20 seconds), not at every dot update;
- genuinely observable backend stages may replace neutral copy, but never invent
  percentages or model-internal progress;
- final durable answer remains an ordinary `sendMessage`;
- `sendChatAction(typing)` remains supplementary/fallback only;
- do not expose a Stop action until real safe cancellation exists.

Initial phrase pool:

1. `Всё ещё работаю над запросом...`
2. `Запрос оказался задумчивее обычного...`
3. `Не пропал — продолжаю разбираться...`
4. `Инвентарь сегодня заставил задуматься...`
5. `Чуть дольше обычного, но я всё ещё здесь...`
6. `Разбираюсь с запросом — ничего нажимать не нужно...`
7. `Задача оказалась с характером...`
8. `Продолжаю, просто этот запрос не из быстрых...`
9. `Всё под контролем, обработка продолжается...`
10. `Ещё немного терпения — запрос всё ещё в работе...`

Progress/draft transport is best effort. Its timeout/retry behavior must be
strictly bounded so progress cannot delay request completion or shutdown.

If live drafts are unavailable, fallback may use one ordinary status message
edited in place and removed/replaced at completion. Never emit a stream of
persistent progress messages.

## Work 5 — meaningful durable failure replies

Fix the current failure path where an application/tool failure may escape before
`send_message` and leave the user with silence while the failed durable request
blocks polling.

Classify failure from authoritative durable request/run state.

### Proven no-mutation failure

When durable state proves no mutation/run was committed, user copy may be:

`Не получилось завершить этот запрос. Я ничего не менял. Попробуйте сформулировать его немного иначе или повторить позже.`

Requirements:

- model/tool failures before any committed mutation become an explicit terminal
  handled-failure outcome;
- after its failure reply is durably handled according to the existing Telegram
  acknowledgement/checkpoint model, the update must not permanently block the
  poller;
- do not weaken request-key replay semantics.

### Uncertain/interrupted failure

When no-mutation cannot be proven, use conservative copy:

`Не получилось завершить запрос. Я остановился, чтобы не внести данные дважды. Запрос сохранён для безопасного восстановления.`

Requirements:

- uncertain request remains recoverable and is not silently acknowledged;
- sending the conservative notice does not authorize replay or mutation;
- repeated poller/recovery behavior must not intentionally spam duplicate failure
  notices; reuse existing durable send/checkpoint machinery or add the smallest
  durable notification state needed.

### Successful mutation + reply transport failure

Preserve existing replay/idempotency semantics. Never execute the mutation twice
merely to resend a Telegram reply.

Never expose exception classes, stack traces, HTTP statuses, provider/model
names, tokens, internal request IDs or recovery commands to the user.

## Work 6 — client/transport bounds

Review new Telegram methods alongside existing retry/timeout behavior.

- progress/draft/edit/callback-answer calls need small bounded timeouts/retries;
- final reply/polling durability rules remain authoritative;
- shutdown must not wait for a long advisory progress request;
- background helpers/threads/tasks must be bounded and cleaned up;
- do not create an unbounded worker per polling cycle;
- secret bot token/chat identity must not leak in exceptions/logs.

## Required regressions

At minimum cover deterministically:

1. compact location rendering with Russian/Unicode names;
2. exact/approximate/unknown quantities;
3. escaping/parse-mode safety and no visible raw `**`;
4. root location list and paging;
5. child drill-down, breadcrumb, Back and All locations;
6. callback authorization/malformed/stale callback handling;
7. stable-ID callback payload rather than display name;
8. same-message editing behavior;
9. progress grace period;
10. dot animation sequence without seconds;
11. all 10 long-wait phrases consumed without repeat before reshuffle;
12. progress transport failure cannot fail/mutate the request;
13. progress cleanup on success, model/tool failure and shutdown;
14. proven no-mutation failure sends safe user copy and does not permanently
    block subsequent polling;
15. uncertain failure remains recoverable and sends only conservative copy;
16. committed mutation + final-send failure does not duplicate mutation;
17. callback/navigation retry cannot mutate inventory;
18. existing Telegram polling/idempotency/recovery tests remain green.

Use fake clocks/synchronization and fake Telegram clients; no real multi-second
sleeps in tests.

## Verification

Run focused Telegram/client/adapter/polling/rendering tests.

Then:

```bash
make compile
git diff --check
```

Exact-head application CI is the repository-wide regression authority.

A bounded live Bot API smoke is allowed only when it cannot mutate production
inventory and the task environment safely provides the existing test bot;
otherwise deterministic client tests are sufficient. Do not expose credentials.

## Independent review emphasis

The reviewer must independently attack:

- hidden mutation paths from callback navigation;
- callback authorization bypass;
- Telegram markup injection/escaping;
- off-by-one paging and stale-location IDs;
- breadcrumb cycles or unbounded hierarchy traversal;
- progress worker/thread leaks and shutdown hangs;
- `sendMessageDraft` misuse or guessed API fields;
- advisory progress calls inheriting long final-message retries/timeouts;
- failure copy claiming “nothing changed” without authoritative proof;
- safe failures still blocking the poller;
- uncertain failures being auto-acked;
- mutation+send failure causing duplicate mutation;
- duplicate failure/progress message spam after retries/restarts;
- model prose still being treated as the authoritative Telegram renderer.

The reviewer is also the correction agent. Reproduce findings where practical,
append regression tests and the narrowest fixes to the same branch, never amend/
rebase/force-push, run focused verification and exact-head CI, then finish with
`REVIEW COMPLETE — CLEAN` or `REVIEW COMPLETE — CORRECTED`.

## Non-goals

- Telegram Mini App;
- multi-user Telegram accounts;
- generic cancellation/Stop semantics;
- streaming partial model answer tokens;
- changing inventory domain semantics;
- Russian canonicalization/entity identity work from #97–#99;
- broad configuration architecture work from #101.

## Handoff

Implementation stops at `READY FOR REVIEW`.

Report exact head, focused checks, Bot API documentation/live evidence used,
PR/CI state and remaining direct follow-ups.
