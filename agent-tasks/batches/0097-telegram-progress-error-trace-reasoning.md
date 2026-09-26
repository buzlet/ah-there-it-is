# Batch: 0097-telegram-progress-error-trace-reasoning

Full local required: `false`

## Objective

Fix the first real production Telegram failure after enabling the reviewed
ChatGPT/Codex provider, make model reasoning effort explicit, and give the user
visible Telegram progress while a request is being processed.

This is a narrow production hotfix/integration batch.

## Production evidence

Reviewed production release before this batch:

`01e624c6e333955275c281a01bcac98e1eba8767`

Production provider:

```text
AH_THERE_IT_IS_LLM_PROVIDER=chatgpt-codex
AH_THERE_IT_IS_LLM_MODEL=gpt-6-luna
```

No application reasoning-effort setting currently exists. The direct provider
request/config path does not currently expose an explicit reasoning effort, so
production is using backend/default behavior rather than an operator-selected
`high` effort.

Telegram production incident:

- user sent ordinary inventory messages;
- Telegram update `587093696` became `failed`;
- `telegram-recovery-status 587093696` reports:
  - `request_status=failed`
  - `request_has_run=false`
  - no recovery attempts;
- the Telegram unit stopped after the durable failed request gate;
- the underlying model/tool path produced a Python `ValueError`:
  `unknown quantity requires a null value`;
- failed-run logging then attempted to persist the raw exception object inside a
  JSON structure;
- SQLite/SQLAlchemy JSON serialization failed with:
  `TypeError: Object of type ValueError is not JSON serializable`;
- this secondary logging failure escaped and crashed the Telegram poller.

The user also observed that while a model request is slow, Telegram shows no
visible indication that work is in progress.

## Product decisions

1. Production model remains `gpt-6-luna`.
2. Production reasoning effort must be explicitly configurable and set to
   `high` after this batch is reviewed/merged.
3. The generic provider contract remains provider-neutral.
4. Error/evaluation traces must always be JSON-safe and secret-safe.
5. Telegram must show an active `typing` chat action for the duration of an
   accepted request, refreshed often enough not to disappear during a long
   model/tool round.
6. Do not fake percentages or token progress. `typing` means only
   “the application is still processing”.
7. Preserve durable Telegram failed-request/recovery semantics. Do not silently
   skip, auto-ack, or automatically replay uncertain failed updates.
8. Do not make production changes from the unreviewed branch.

## Scope

### 1. Explicit reasoning effort

Add the smallest provider-neutral/config-safe setting required to configure
reasoning effort, conceptually:

```text
AH_THERE_IT_IS_LLM_REASONING_EFFORT=high
```

Requirements:

- validate a narrow supported set based on the current ChatGPT/Codex Responses
  contract; do not accept arbitrary strings;
- map it only where supported by the direct ChatGPT/Codex provider;
- use the correct current Responses request shape as established from official
  Codex/OpenAI source/docs or live behavior;
- include the non-secret effort value in `LLMClientInfo.config`/trace metadata;
- never infer effort from the executor model;
- existing providers remain behavior-compatible;
- deterministic tests inspect the exact outgoing payload;
- run a bounded live `gpt-6-luna` probe with `high` through the normal factory
  path.

Do not add hidden/default `high` globally. Production activation happens only
after review/merge.

### 2. JSON-safe failure traces

Fix the failure path so no arbitrary Python exception/object can enter a JSON
column.

Requirements:

- failed model/tool traces are recursively converted to deterministic JSON-safe
  values before persistence;
- exception values retain useful bounded diagnostics, normally exception type
  plus sanitized message;
- no secrets, repr memory addresses, arbitrary object serialization hooks, or
  unserializable values;
- mappings/sequences/nested tool traces are handled;
- normal successful traces keep their existing shape where already JSON-safe;
- do not stringify the entire trace wholesale;
- the original application/tool failure remains the reported failure; a
  secondary evaluation/logging failure must not replace it;
- add a regression reproducing the production shape containing
  `ValueError("unknown quantity requires a null value")`.

Review adjacent persistence paths for the same JSON-safety bug and apply one
small shared boundary helper if appropriate.

### 3. Telegram visible progress

Implement Telegram Bot API `sendChatAction` with action `typing`.

Behavior:

- once a private text update from the allowed user is accepted for processing,
  send `typing` promptly;
- while model/tool processing is still active, refresh it before Telegram's
  typing indicator expires (use a conservative interval, e.g. around 4s);
- stop refreshing immediately on success or failure;
- do not send typing for rejected/foreign/non-text updates;
- a transient typing-action transport failure must not corrupt inventory or
  turn an otherwise valid request into an uncertain mutation;
- bound/reuse the existing Telegram transport rules;
- avoid leaking the bot token/chat identity in errors;
- do not spawn an unbounded thread/process per poll cycle;
- ensure cleanup on exception and shutdown;
- preserve single-user polling and durable acknowledgement semantics.

A small context manager/background helper around one accepted update is
preferred over mixing progress scheduling into the agent/provider layer.

### 4. Failure visibility

The primary requirement is a persistent/refreshing Telegram typing indicator.
Also inspect the failure path for whether a safe user-visible failure message
can be sent without weakening durable recovery semantics.

If a safe message is added, it must state only that processing failed/stopped
and must not claim a mutation was or was not committed unless that fact is
authoritatively known. Do not auto-ack the failed update merely to send it.

If this cannot be done safely in this batch, document that recovery remains an
operator action; do not broaden scope.

### 5. Production incident recovery proof

Using a scratch DB / deterministic fixture, reproduce:

1. accepted Telegram update;
2. tool/model failure containing a real Python exception in trace metadata;
3. failure trace persists JSON-safely;
4. request remains recoverable according to existing semantics;
5. poller does not die from JSON serialization itself.

Do not operate on production update `587093696` from the implementation branch.

### 6. Tests

At minimum cover:

- config parsing/validation for reasoning effort;
- exact direct-provider request body for `high`;
- info/trace metadata contains safe effort value;
- current Luna capability behavior remains intact;
- recursive JSON-safe conversion including nested Exception values;
- production `ValueError` regression;
- no secret exposure in converted errors;
- `sendChatAction` request mapping;
- typing starts only for an accepted allowed private text update;
- refresh behavior for a long-running operation using deterministic fake clock/
  synchronization rather than real multi-second sleeps;
- typing cleanup on success and exception;
- typing transport failure does not alter request atomicity;
- existing Telegram recovery/idempotency tests;
- provider/runner regressions from 0096.

Then run:

```bash
make compile
git diff --check
```

Exact-head CI is the repository-wide regression authority.

## Live evidence

On U24 as `rdu01`:

- use existing Codex-managed ChatGPT login;
- run one bounded normal-factory direct provider smoke with:
  - model `gpt-6-luna`
  - reasoning effort `high`;
- do not mutate production inventory during the probe;
- do not expose auth state.

Do not activate the work branch in production.

## Acceptance

Accept when:

- application has an explicit validated reasoning-effort setting;
- direct Luna request demonstrably sends `high`;
- raw Python exceptions can no longer break JSON persistence;
- the exact production-style ValueError regression passes;
- accepted Telegram requests visibly maintain `typing` while processing;
- progress cleanup is bounded/reliable;
- durable failed-update semantics remain intact;
- exact-head CI is green;
- PR is ready for independent review.

## Post-review orchestration

After independent review and merge, orchestrator will:

1. deploy exact merged main;
2. set production:
   `AH_THERE_IT_IS_LLM_PROVIDER=chatgpt-codex`
   `AH_THERE_IT_IS_LLM_MODEL=gpt-6-luna`
   `AH_THERE_IT_IS_LLM_REASONING_EFFORT=high`;
3. restart web/Telegram;
4. run provider smoke;
5. inspect production recovery status for update `587093696`;
6. only because current authoritative status is `request_has_run=false`, execute
   the normal explicit recovery workflow if still applicable;
7. verify Telegram replies and typing behavior.

## Non-goals

- fake percentage/token progress;
- streaming partial model text into Telegram;
- OAuth changes;
- model change away from Luna;
- Telegram multi-user support;
- changing recovery/idempotency semantics;
- batch 0094 work.

## Handoff

Stop at `READY FOR REVIEW`.

Report implementation SHA, exact tests, live Luna/high evidence, PR/CI, and any
remaining recovery/operator step.
