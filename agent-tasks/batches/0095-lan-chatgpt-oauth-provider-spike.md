# Batch: 0095-lan-chatgpt-oauth-provider-spike

Full local required: `false`

## Objective

Advance the usable MVP in two independent directions without reopening inventory product
semantics:

1. prepare the production web service to listen continuously on the trusted development
   LAN rather than loopback only; and
2. design, implement, and deeply verify an isolated ChatGPT-subscription provider module
   that fits the existing provider-neutral `LLMClient` boundary, using the current
   ChatGPT/Codex OAuth access token already maintained by Codex, while keeping this new
   provider out of the production provider factory until a later integration batch.

The provider work is intentionally a long-running research + implementation spike.
It must end with enough evidence to choose the next integration path rather than with a
premature production switch.

Batch 0094 (systemic CI/test scalability) is parked and non-blocking. Do not modify,
finish, depend on, or otherwise couple this work to 0094.

## Product decisions already made

These are requirements, not questions for the agent to reopen.

### Trusted-LAN web exposure

The target environment is a trusted development machine on a trusted private network.

The web application may intentionally listen on all interfaces for this environment.
Do not add authentication, reverse proxying, TLS, VPN, account/role infrastructure, or
firewall management in this batch.

Keep the existing explicit non-loopback safety acknowledgement. The desired production
command is conceptually:

```text
ah-there-it-is serve --host 0.0.0.0 --port 8000 --allow-nonlocal
```

Do not weaken the CLI default: an accidental non-loopback bind without
`--allow-nonlocal` must continue to fail.

### ChatGPT/Codex credential ownership

The application does **not** own OAuth login or token refresh.

Use the current ChatGPT access token already present in the Codex credential cache.
Codex itself is responsible for keeping its own login usable.

For the provider implemented in this batch:

- read the existing access token;
- re-read the credential source on later requests so a Codex-updated cache is observed;
- never call the OAuth token endpoint;
- never use the refresh token;
- never write, rewrite, chmod, rotate, delete, copy, or otherwise mutate Codex
  `auth.json`;
- never run `codex login`, `codex logout`, or an explicit refresh operation as part of
  provider behavior;
- on authentication failure, fail clearly and safely rather than attempting refresh.

The credential source must remain replaceable/testable. Reading a file directly from the
HTTP transport is not an acceptable design.

### Integration boundary

The new provider must be designed to fit the existing:

```python
class LLMClient(Protocol):
    @property
    def info(self) -> LLMClientInfo: ...

    def complete(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
    ) -> LLMResponse: ...
```

However this batch is **standalone-provider-first**.

Do not register the new provider in `agent/factory.py`.
Do not select it in production `runtime.env`.
Do not make production Web or Telegram depend on it.
Do not change the current production heuristic provider.

A later batch will perform application integration only after this module has independent
evidence.

## Starting evidence

Treat this as starting evidence to verify, not as a substitute for current-source
inspection.

Official OpenAI material currently distinguishes two Codex authentication paths:

- ChatGPT sign-in for subscription access;
- API-key sign-in for usage-based OpenAI Platform access.

Official Codex material also documents that ChatGPT-authenticated Codex uses the
ChatGPT/Codex Responses endpoint, while API-key Codex uses the public OpenAI Responses
API.

Current public implementations and issue evidence indicate:

- a ChatGPT/Codex OAuth access token from the Codex cache is accepted by
  `https://chatgpt.com/backend-api/codex/responses`;
- the same class of ChatGPT OAuth token is generally rejected by
  `https://api.openai.com/v1/responses` because it lacks Platform API scopes such as
  `api.responses.write`;
- third-party projects use the Codex credential cache directly against the ChatGPT/Codex
  backend;
- examples worth inspecting include Simon Willison's `llm-openai-via-codex`,
  OpenCode/Codex-auth implementations, and Codex Responses proxy projects;
- the ChatGPT/Codex backend is Responses-shaped but is not identical to the public
  Platform API contract; current implementations commonly require `store: false`,
  streaming, and ChatGPT account identity headers;
- the backend and Codex CLI behavior have changed over time, so copied request recipes
  are not sufficient evidence.

The batch must reproduce the relevant facts on the actual current Codex login available
to the executor.

## Scope

Allowed:

- deployment unit/runbook/tests needed for trusted-LAN web exposure;
- read-only inspection of the existing Codex auth cache;
- read-only inspection of current Codex CLI configuration/version/login status;
- current official OpenAI/Codex documentation and open-source Codex source inspection;
- current third-party open-source implementation research;
- small bounded live requests using the existing ChatGPT/Codex access token;
- a minimal A/B authentication probe against public OpenAI Responses and the
  ChatGPT/Codex Responses backend;
- standalone provider modules implementing the project's existing `LLMClient` contract;
- standalone provider-specific probes/CLIs;
- fake HTTP/SSE servers and deterministic unit/integration tests;
- a second experimental provider path that invokes `codex exec` as a subprocess;
- focused evaluation of text, structured tool selection, tool-result continuation,
  errors, secret redaction, timeout behavior, and latency;
- a durable non-secret research/decision document.

Not allowed:

- changing inventory/domain semantics;
- changing the provider-neutral agent runner contract merely to fit Codex;
- OAuth login implementation;
- OAuth refresh implementation;
- persisting/copying the refresh token;
- committing any credential/token/account secret;
- printing or intentionally logging access-token contents;
- exposing raw auth-cache contents in PR text, test output, screenshots, artifacts, or
  research documents;
- production provider activation;
- Telegram activation/configuration;
- model auto-promotion for the application;
- 0094 CI architecture work;
- broad CI-runtime optimization;
- new application authentication or multi-user support.

## Work

### 1. Establish the exact current provider boundary

Before implementing a new adapter, inspect the current application provider architecture:

- `agent/protocol.py`;
- `agent/runner.py`;
- `agent/factory.py`;
- `agent/openai_compatible.py`;
- `agent/gemini.py`;
- `agent/metadata.py`;
- provider smoke/evaluation modules;
- relevant provider and runner tests.

Record the invariants the new standalone module must preserve:

- `LLMClientInfo` contains only safe metadata;
- credentials never enter persisted metadata;
- one `complete()` call receives the complete message history needed for that round;
- generic `AgentMessage`, `ToolDefinition`, `ToolCall`, and `LLMResponse` remain
  provider-neutral;
- malformed provider responses fail closed;
- the model never writes the inventory directly;
- tool execution remains owned by the existing agent runner/application.

Do not change these invariants unless a concrete incompatibility is demonstrated and
reported as a blocker.

Checkpoint after the architectural inspection and any test fixture preparation.

### 2. Prepare trusted-LAN web exposure

Change the shipped stable web unit so the intended production service listens on all
interfaces:

```text
--host 0.0.0.0 --port 8000 --allow-nonlocal
```

Requirements:

- preserve the CLI's current loopback-safe default;
- preserve the explicit `--allow-nonlocal` requirement;
- do not add auth/TLS/reverse-proxy/firewall behavior;
- update deployment/runbook statements that currently say the service binds only
  `127.0.0.1`;
- state explicitly that this deployment profile assumes a trusted private development
  network and the web UI has no application authentication;
- update structural/deployment tests that validate the effective unit command;
- preserve Telegram credential unsetting in the web unit;
- preserve schema preflight, stable copied units, restart behavior and all 0091/0093
  deployment invariants.

Do not switch the active production release to an unreviewed branch merely to test this
change.

Validate the bind behavior safely using a temporary/scratch instance or equivalent
non-production-data method:

- prove loopback health;
- prove the process listens non-loopback;
- when practical, probe the host's own LAN address;
- do not alter host firewall rules;
- if true remote-host reachability cannot be proven from the executor, report that as a
  small post-merge operator verification rather than inventing evidence.

Checkpoint after LAN code/tests/docs are focused-green.

### 3. Inspect the current Codex authentication state safely

Determine, without revealing secret values:

- Codex CLI version;
- whether `codex login status` reports ChatGPT authentication;
- credential storage mode if discoverable without mutation;
- effective `CODEX_HOME`;
- whether a file-backed auth cache is available;
- auth mode;
- whether an access token is present;
- whether an account/workspace identifier needed by current backend requests is present
  or derivable;
- current/default Codex model configuration, if safely available.

Do not print:

- access token;
- refresh token;
- id token;
- full auth JSON;
- bearer headers;
- secret-bearing request dumps.

If the Codex credential is not file-backed, research whether a safe read-only interface
exists for obtaining the current access credential. Do not change credential storage
just to make this batch easier. If no safe read-only credential access exists, the direct
backend path may stop with evidence while the subprocess path continues.

Checkpoint the non-secret discovery tooling/tests if repository changes were needed.

### 4. Research the current authentication/backend contract

Inspect current primary sources first:

- current OpenAI Codex authentication documentation;
- current OpenAI explanation/source for Codex inference/auth routing;
- current `openai/codex` source that chooses the ChatGPT backend, builds request headers,
  model catalog requests and Responses requests;
- current `codex exec` non-interactive behavior/options.

Then inspect at least three independent third-party implementations that consume a
ChatGPT/Codex subscription outside the stock Codex TUI.

At minimum include, if still current/available:

- `simonw/llm-openai-via-codex`;
- one OpenCode/Codex OAuth implementation;
- one Codex Responses proxy/SDK implementation.

For each, extract only non-secret protocol facts:

- credential source;
- endpoint;
- required headers;
- account ID handling;
- model discovery;
- request fields added/removed;
- streaming requirements;
- `store` behavior;
- function/tool representation;
- response/SSE parsing;
- conversation/tool continuation strategy;
- token refresh behavior (for comparison only; do not copy it into our implementation);
- known limitations and backend assumptions.

Write a durable research artifact, for example:

`docs/research/chatgpt-codex-oauth-provider.md`

The document must separate:

- official/documented facts;
- facts established from OpenAI open-source Codex source;
- third-party implementation conventions;
- facts reproduced live in this batch;
- assumptions/unstable behavior.

No secrets or token-derived identifying information may appear in the document.

### 5. Perform a bounded public-API vs Codex-backend A/B probe

Use the **same existing current access token** through an in-process probe so the bearer
value never appears in argv/shell history.

Do not refresh it.

#### Probe A: public OpenAI Responses API

Issue one minimal harmless request to:

`https://api.openai.com/v1/responses`

using the current ChatGPT/Codex OAuth bearer.

Use a currently available model/request shape only after checking current documentation.
The purpose is authentication capability detection, not model benchmarking.

Capture only:

- endpoint class;
- HTTP status;
- safe error code/message with credential redaction;
- whether the endpoint accepted authentication;
- whether a response could be produced.

If authentication succeeds unexpectedly, perform one additional minimal structured/tool
capability probe so we can determine whether this path can satisfy our `LLMClient`
contract.

Do not infer success from a redirect or a different endpoint.

#### Probe B: ChatGPT/Codex Responses backend

Issue a minimal harmless request to the current backend used by ChatGPT-authenticated
Codex.

Derive the current request shape/headers from current Codex source and live evidence,
not from stale snippets.

At minimum establish:

- bearer accepted/rejected;
- account identity header requirements;
- model availability;
- `store` requirement;
- streaming requirement;
- whether ordinary text output works.

#### Decision gate

Classify the result:

**Path P — public Responses usable with this ChatGPT OAuth token**

Only choose this if the public `api.openai.com` endpoint actually authenticates the
current token and provides the capabilities needed for our provider contract.

If Path P is real, prefer it architecturally over the Codex-specific backend.

**Path C — public Responses rejects the token, ChatGPT/Codex backend works**

This is the currently expected result. Continue with an isolated direct Codex-backend
transport.

**Path N — neither direct endpoint is usable**

Continue researching the `codex exec` subprocess path. Do not fabricate a direct
transport.

Document the exact non-secret evidence for the gate.

### 6. Implement a replaceable read-only credential source

Create a small credential abstraction independent of HTTP transport.

A suitable design is conceptually:

```python
@dataclass(frozen=True)
class ChatGPTCredentials:
    access_token: str
    account_id: str | None

class ChatGPTCredentialSource(Protocol):
    def get(self) -> ChatGPTCredentials: ...
```

Exact names are implementation choices.

Provide:

- a production read-only source for the current Codex credential cache when available;
- a deterministic static/fake source for tests.

File-source requirements:

- configurable explicit auth-file/Codex-home path at construction time;
- sensible Codex-home default only inside the credential source;
- validate expected JSON shape;
- accept only the intended ChatGPT auth mode for this provider;
- extract only fields required for access;
- re-read on each `get()` (or an equivalently simple mechanism that observes a Codex
  rewrite without application restart);
- never return refresh token;
- never expose id token unless a demonstrated current backend requirement makes it
  necessary; if account ID can be read directly, prefer that;
- never modify the file;
- never attempt refresh;
- sanitize parse/configuration errors so token material cannot be embedded in them.

Tests must prove the auth file is byte-for-byte unchanged after reads and after simulated
authentication failures.

Checkpoint after credential-source tests are green.

### 7. Implement the preferred direct Responses provider as a standalone module

Implement a new adapter that conforms to the existing `LLMClient` protocol but remains
unregistered in the production factory.

Naming should reflect the established live path rather than an assumption. Examples:

- public path: `ChatGPTOAuthResponsesLLMClient`;
- Codex path: `ChatGPTCodexLLMClient`.

Do not force these exact names.

#### Transport

The adapter must:

- obtain a fresh snapshot from the credential source for every independent request;
- use an owned/reusable HTTP client where appropriate;
- never place bearer values in safe metadata;
- never put bearer values in exception messages;
- never retry 401/403 by refreshing credentials;
- allow only bounded transient retries for statuses where retry is actually appropriate;
- bound request timeout;
- bound response/SSE accumulation;
- close owned network resources cleanly.

For the Codex backend path:

- use the current required ChatGPT account header if established;
- use `store: false` when required;
- use streaming when required;
- consume SSE robustly;
- do not assume a non-stream JSON response is available;
- do not implement WebSocket transport in this batch unless HTTP/SSE is demonstrably
  unavailable and WebSocket is necessary to complete the spike.

#### Message/tool mapping

Map the generic application contract to Responses semantics without leaking Codex
concepts into the rest of the application.

Support at minimum:

- system instructions;
- user text;
- assistant text;
- prior assistant tool/function calls;
- tool results;
- tool definitions with JSON Schema;
- zero or more returned tool calls;
- final text;
- safe response metadata.

Prefer reconstruction from the full `messages` sequence supplied to `complete()` over
server-side conversation storage. The project already gives the adapter the complete
current-round history.

Do not depend on `previous_response_id` or remote persistence merely for convenience
when `store: false` and full-history reconstruction can satisfy the contract.

If opaque provider-only state is genuinely needed inside one tool loop, use the existing
provider-state isolation pattern and prove it does not persist into generic traces.

#### SSE/Responses parsing

Test realistic event fragmentation:

- multiple SSE events in one TCP chunk;
- one event split across chunks;
- comments/blank lines;
- completed response;
- output text deltas/final text;
- function-call arguments delivered incrementally;
- multiple calls;
- provider error event;
- premature EOF;
- malformed JSON;
- oversized response.

Fail closed on incomplete tool-call arguments.

Checkpoint after deterministic direct-adapter tests.

### 8. Build standalone direct-provider probes

Add an explicit standalone probe/command that exercises the adapter without Inventory,
FastAPI, Telegram, or the production DB.

It must not be wired through `agent/factory.py`.

Provide at least these live scenarios:

#### Text

System:

```text
Reply briefly and do not call tools.
```

User requests a small deterministic marker.

Require non-empty text.

#### Native tool selection

Expose a synthetic read-only tool such as:

`lookup_item(name: str)`

Ask a Russian inventory question that clearly requires that tool.

Require a structured `ToolCall` rather than parsing tool intent from prose.

#### Multi-round tool continuation

1. model chooses `lookup_item`;
2. the probe returns a synthetic result such as a location;
3. call the adapter again with the complete generic message history;
4. require a coherent final answer.

No real inventory mutation is allowed.

#### No-tool path with tools available

Expose tools but use a question that should be answered without one.
Ensure the adapter can return plain text.

Record model identity, safe backend identity, wall time and outcome.
Do not record credentials.

### 9. Investigate and implement the `codex exec` subprocess alternative

This is an independent experimental backend.

The goal is to determine whether delegating inference/auth/backend compatibility to the
installed Codex CLI is a viable fallback even though it has more process overhead and is
oriented toward coding-agent use.

Do not assume it is viable; prove or reject it.

#### Research current non-interactive interface

Inspect current:

- `codex exec --help`;
- official non-interactive documentation;
- JSON event mode;
- ephemeral mode;
- output-schema support;
- model selection;
- sandbox/approval options;
- working-directory behavior;
- exit codes;
- timeout/cancellation behavior.

Determine whether there is a supported way to make the subprocess act as a bounded
model call rather than as an unrestricted coding agent.

#### Isolation requirements

The subprocess provider must not be allowed to mutate the application repository or
production data merely because Codex has agent tools.

Use the strongest practical isolation supported by the current CLI, including as
appropriate:

- ephemeral session;
- dedicated empty temporary working directory;
- read-only sandbox;
- no approval escalation;
- no inherited application secrets beyond what Codex itself requires;
- no production database path in the prompt/environment;
- bounded subprocess runtime;
- process-group termination on timeout.

Do not use `shell=True`.

If Codex cannot be prevented from executing its own shell/file tools, detect/report
that fact. A subprocess provider that can unexpectedly operate on the host is not an
acceptable transparent `LLMClient` replacement.

#### Generic contract mapping

Try to implement a second standalone `LLMClient`-compatible adapter.

Preferred approach:

- send the generic message history and tool definitions as model context;
- require a strict structured output schema representing either:
  - assistant text; or
  - one or more generic tool calls;
- parse the final structured result into `LLMResponse`;
- on the next call, include the tool result in the supplied history.

This path is allowed to emulate tool selection through structured model output if
`codex exec` does not expose our dynamic tools natively, but the limitation must be
documented clearly.

Do not let Codex execute the inventory tool itself. The existing application runner owns
all inventory tool execution.

Use current structured-output/output-schema facilities where possible rather than
free-form regex parsing.

#### JSON event supervision

If `--json` is used, inspect event streams for evidence that Codex executed internal
shell/file/web tools.

Treat unexpected internal tool execution as a provider-safety failure for this use case
unless it can be disabled reliably.

Bound captured stdout/stderr and redact secrets from errors.

Checkpoint after deterministic subprocess tests and live basic probe.

### 10. Compare direct and subprocess paths empirically

Run a bounded comparison on the same available model where practical.

Do not burn quota on a huge benchmark. Use enough repetitions to identify fixed
subprocess overhead and obvious instability.

At minimum compare:

- three simple text calls;
- three tool-selection calls;
- three multi-round synthetic-tool scenarios.

Capture:

- success/failure;
- model used;
- backend path;
- total wall time;
- time to first useful event if observable without invasive instrumentation;
- subprocess startup overhead where applicable;
- request/retry count;
- malformed-output count;
- internal Codex tool-use count for subprocess path;
- whether the generic `LLMClient` semantics were preserved.

Do not claim statistically precise performance from this small sample.
Report raw measurements and median when useful.

### 11. Exercise adversarial/error boundaries

For both implementations where applicable, cover:

- missing credential file;
- wrong auth mode;
- missing access token;
- malformed auth JSON;
- missing account ID when backend requires it;
- HTTP 401;
- HTTP 403;
- HTTP 429;
- transient 5xx;
- timeout;
- connection failure;
- malformed SSE;
- truncated SSE;
- malformed tool arguments;
- multiple tool calls;
- nonzero `codex exec` exit;
- subprocess timeout;
- unexpected subprocess output;
- output larger than configured bound;
- token-like secret text returned in an upstream error body.

Assertions must prove token redaction.

A 401/403 must **not** trigger token refresh.

### 12. Check compatibility with the project's agent runner using only synthetic data

Without registering the provider in the production factory, instantiate the new direct
client explicitly in focused tests/probes and run it through the existing bounded
`AgentRunner` machinery where possible.

Use a scratch/in-memory/test database or fully synthetic tools only.

Prove:

- runner sees ordinary `LLMResponse`;
- structured tool call reaches the existing tool boundary;
- tool result returns to the provider in the next round;
- max-round protection still works;
- provider error does not partially commit a mutation;
- provider-specific state does not contaminate persisted trace fields.

For live tests, prefer read-only/synthetic tools.
Do not populate the production inventory.

### 13. Inspect model catalog/selection behavior without promoting a model

Determine how current ChatGPT/Codex auth exposes usable models:

- current Codex CLI model/default;
- current Codex model-catalog endpoint/source if safely usable;
- direct backend model names accepted during this spike;
- any request-shape differences relevant to current GPT-5.6 family models.

Do not hardcode a broad stale allowlist if live/model-source discovery is simple.
Do not change the application's production model selection.

The research document should identify which model(s) were actually used for evidence and
which behavior appears model-specific.

### 14. Produce an explicit architecture decision for the later integration batch

At the end, classify the candidates:

#### Candidate A — public OpenAI Responses with ChatGPT OAuth bearer

Criteria:

- current token accepted by `api.openai.com`;
- text works;
- tool calling works;
- generic contract can be implemented without Codex-specific wire behavior.

If all true, recommend this for later integration.

#### Candidate B — direct ChatGPT/Codex Responses backend

Criteria:

- current token accepted;
- stable text + native tool calls + tool-result continuation;
- reasonable latency;
- request shape can be isolated in one adapter;
- no token refresh code required;
- current backend requirements are covered by tests.

If A is unavailable and B passes, recommend B.

#### Candidate C — `codex exec` subprocess

Criteria:

- can operate non-interactively and safely;
- no unintended host tool execution;
- structured output reliably maps to our tool-call contract;
- timeout/cancellation is bounded;
- latency is acceptable as a fallback.

Treat C primarily as fallback unless evidence makes it clearly preferable.

#### No viable candidate

If none passes, do not integrate a broken approximation.
State the blockers and preserve the research/tests that established them.

The decision must be based on reproduced evidence, not preference.

### 15. Keep the module isolated from production integration

Before finalizing, verify this batch did **not**:

- add the new provider name to `build_llm_factory()`;
- change production provider configuration;
- add ChatGPT OAuth values to `runtime.env`;
- change Telegram;
- teach the generic application to read Codex auth directly;
- add refresh behavior;
- depend on Codex CLI from ordinary application startup;
- add Codex as a mandatory package dependency for existing providers.

Standalone provider code and probes may depend on Codex being present only for the
subprocess experiment.

### 16. Documentation

Update documentation needed for LAN exposure.

Add the provider research/decision document with:

- problem statement;
- current official auth split;
- token-source constraints;
- public-API A/B result;
- direct backend contract observed;
- third-party implementation survey;
- direct adapter design;
- subprocess adapter design;
- live test evidence;
- latency table;
- security/redaction behavior;
- known backend instability/version coupling;
- recommendation for the later integration batch;
- exact remaining work for that later integration.

Do not include secret-bearing command examples.

## Testing expectations

Prefer focused checkpoints over one giant end-of-batch debug cycle.

Suggested checkpoint sequence:

1. LAN unit/docs/tests;
2. credential source;
3. direct transport fake-server tests;
4. direct generic mapping tests;
5. direct live probe;
6. subprocess deterministic tests;
7. subprocess live probe;
8. runner compatibility;
9. comparison/research document;
10. final cleanup/verification.

The exact commit grouping may differ, but ordinary commits should provide useful recovery
points for a long unattended run.

### Required focused tests

At minimum include focused coverage for:

- non-loopback serving guard remains intact;
- shipped web unit contains explicit LAN bind + acknowledgement;
- stable-unit installer verification accepts the intended command and still checks
  security/environment boundaries;
- credential source read-only behavior;
- no refresh behavior;
- redaction;
- direct request mapping;
- direct SSE parsing;
- direct tool call mapping;
- direct multi-round mapping;
- direct error mapping;
- subprocess argv/environment construction;
- subprocess timeout/kill;
- subprocess structured-output parsing;
- unexpected internal Codex tool execution detection when applicable;
- generic runner compatibility.

Use local fake HTTP/SSE servers for deterministic transport behavior.
Do not make ordinary unit tests depend on live ChatGPT/OpenAI services.

## Live-call policy

Live calls are explicitly allowed in this batch because they are the object of the
research.

Keep them:

- bounded;
- non-mutating with respect to production inventory;
- free of sensitive prompt content;
- small enough not to waste account quota;
- manually/focused invoked rather than part of ordinary CI.

Never commit live response bodies when they contain account-specific metadata.
Store only sanitized evidence.

## Security requirements

Treat Codex auth material like a password.

Never:

- print auth JSON;
- print bearer values;
- put token in command-line argv;
- put token in committed environment examples;
- persist token in test fixtures;
- send token to any host other than the explicitly tested OpenAI endpoints;
- include token/account identifiers in PR body;
- dump complete HTTP headers.

Errors from upstream must be redacted against the current access token before becoming
application-visible or test/log output.

For subprocess execution, avoid passing application secrets that Codex does not need.

## Acceptance

The batch is acceptable only when all applicable items below are evidenced.

### LAN

- shipped web unit requests `0.0.0.0:8000` with `--allow-nonlocal`;
- default CLI behavior remains loopback-safe;
- focused deployment tests pass;
- scratch/host bind probe proves the intended listener behavior;
- docs state trusted-LAN/no-auth assumption accurately.

### Auth research

- current Codex login mode safely identified;
- current access credential can be read without mutation, or direct-path blocker is
  documented;
- public Responses API A/B result recorded;
- ChatGPT/Codex backend result recorded;
- no refresh performed by our code;
- at least three third-party implementations surveyed.

### Direct adapter

- implements `LLMClient` semantics;
- deterministic fake transport tests green;
- live text call green;
- live structured native tool selection green;
- live synthetic tool-result continuation green;
- 401 does not refresh;
- credential redaction proved.

### Subprocess adapter

If viable:

- deterministic subprocess tests green;
- live text call green;
- structured tool-selection representation works;
- multi-round synthetic tool flow works;
- timeout/process cleanup works;
- unintended Codex internal tool behavior is either disabled or detected.

If not viable, the exact safety/semantic blocker is reproduced and documented.

### Comparison

- bounded repeated timing evidence exists;
- direct vs subprocess trade-offs are explicit;
- recommendation for the next integration batch is explicit and evidence-based.

### Isolation

- no production provider wiring;
- no production DB mutation;
- no Telegram change;
- no OAuth refresh implementation;
- no secret committed.

## Final verification

Before handoff:

```bash
make compile
git diff --check
```

Run all focused tests introduced/affected by this batch.

Because `full_local_required: false`, do not spend this batch running or optimizing a
large local full regression merely to satisfy an arbitrary wall-clock target.

Open one PR from the work branch.
Obtain authoritative exact-head application CI for repository changes.

If the ordinary CI architecture is still the pre-0094 architecture, accept its current
behavior; do not turn this batch into CI scalability work.

Inspect the complete issuance-to-head diff and verify:

- this task file is unchanged;
- no credentials are present;
- no accidental production provider integration occurred;
- the branch is clean.

## Non-goals / stop conditions

- Do not complete parked batch 0094.
- Do not redesign inventory/product behavior.
- Do not add app authentication.
- Do not add a reverse proxy.
- Do not manage firewall/router configuration.
- Do not implement OAuth login.
- Do not implement access-token refresh.
- Do not mutate Codex auth state.
- Do not make `codex exec` a mandatory runtime dependency.
- Do not enable the provider in production.
- Do not enable Telegram.
- Do not choose a permanent production model.
- Do not weaken secret redaction.
- Do not work around a broken endpoint by silently falling back to a different paid API
  credential.
- Do not use an unrelated `OPENAI_API_KEY` as evidence that the ChatGPT OAuth token
  works.
- Do not claim public API compatibility unless the same ChatGPT/Codex OAuth access token
  itself is accepted there.
- Do not claim a subprocess provider is safe if Codex can unexpectedly execute host
  tools and that behavior cannot be reliably prevented/detected.

Stop and report if:

- live auth is unavailable and neither direct nor subprocess evidence can be obtained;
- completing the work requires OAuth refresh/login changes contrary to this task;
- the only viable solution would require changing product semantics;
- a real secret is accidentally exposed in a committed artifact (remove it from the
  branch history before publication and report the incident safely).

## Handoff

Implementer stops at:

`READY FOR REVIEW`

Final handoff must include only non-secret information:

- implementation head SHA;
- LAN exposure status;
- public Responses OAuth A/B result;
- direct ChatGPT/Codex backend result;
- direct adapter live result;
- `codex exec` adapter result;
- models used for testing;
- bounded latency comparison;
- exact focused verification performed;
- PR and exact-head CI status;
- recommendation for the later integration batch;
- remaining technical blockers/risks.

Reviewer is an independent role.

Review the exact implementation head without using the implementer's conclusions as a
checklist. Reconstruct requirements from this task and protocol.

Neither implementer nor reviewer merges.
