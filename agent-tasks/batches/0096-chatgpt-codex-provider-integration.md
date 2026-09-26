# Batch: 0096-chatgpt-codex-provider-integration

Full local required: `false`

## Objective

Integrate the already-reviewed direct ChatGPT/Codex Responses adapter from batch 0095
into the application's normal provider configuration and factory boundary, while
preserving the application's provider-neutral architecture and the read-only ownership
model for Codex credentials.

This is an integration batch, not another protocol-research spike.

Batch 0094 remains parked and non-blocking.

## Starting point

Main includes reviewed batch 0095 and its reviewer corrections.

Relevant reviewed components already exist:

- direct ChatGPT/Codex Responses adapter;
- read-only Codex credential source;
- standalone live probe;
- `codex exec` experimental fallback adapter;
- trusted-LAN web unit;
- research evidence in `docs/research/chatgpt-codex-oauth-provider.md`.

0095 established on the target host that:

- the current ChatGPT/Codex OAuth access token is not accepted by public
  `api.openai.com/v1/responses`;
- the direct ChatGPT/Codex Responses backend accepts it;
- direct text, native tool selection and multi-round continuation work;
- no application-side OAuth refresh is required or allowed;
- direct transport is the preferred application candidate;
- `codex exec` is a fallback/debug experiment, not the preferred runtime backend.

The 0095 reviewer corrected four issues around bounded secret redaction, overall stream
timeout, incomplete `codex exec` turn acceptance and subprocess descendant cleanup.
Do not regress those fixes.

## Product decisions

1. Production integration uses the **direct ChatGPT/Codex Responses adapter**.
2. Do not register `codex exec` as a normal production provider.
3. The application continues to use the existing generic `LLMClient` contract.
4. Codex remains owner of ChatGPT login and credential lifecycle.
5. The application only reads the existing current access credential.
6. No OAuth login/refresh/write implementation is allowed.
7. The production model remains an explicit operator configuration value. Do not infer a
   permanent model from the executor's own model or from Codex defaults.
8. Telegram is outside this batch.
9. Do not activate an unreviewed branch as the production release.

## Scope

Allowed:

- configuration fields needed to select the reviewed direct provider;
- provider factory registration;
- safe provider-specific validation;
- provider smoke integration;
- model/backend metadata needed for safe runtime behavior;
- focused tests and documentation;
- bounded live provider probes using existing Codex login;
- deployment documentation for selecting this provider after merge;
- cleanup/refactoring strictly necessary to make the reviewed adapter a normal provider.

Not allowed:

- OAuth refresh/login;
- writing Codex auth state;
- `codex exec` as a production factory choice;
- production release switch before review/merge;
- Telegram activation;
- inventory/domain semantics changes;
- app authentication/reverse proxy/TLS work;
- 0094 CI scalability work;
- broad model benchmarking;
- silent fallback to API-key OpenAI Platform access;
- automatic permanent model selection.

## Work

### 1. Re-read the reviewed provider contract

Inspect the integrated 0095 implementation and reviewer correction before changing
factory/configuration code.

Confirm the direct adapter still:

- re-reads current credential state;
- never refreshes;
- never exposes bearer/account values in metadata/errors;
- enforces bounded total stream time;
- rejects malformed/incomplete streams;
- maps native tool calls/results to generic protocol values;
- reconstructs multi-round history without remote conversation persistence.

Do not rewrite working transport code without a concrete integration need.

### 2. Add explicit application configuration

Introduce only the minimum settings needed for the normal application to construct the
direct provider.

Use an explicit provider selector, conceptually:

```text
AH_THERE_IT_IS_LLM_PROVIDER=chatgpt-codex
```

The existing `AH_THERE_IT_IS_LLM_MODEL` remains the explicit model selector.

Add only a credential-location setting if the reviewed credential source actually needs
one at application construction time. Prefer a Codex-home style path over a token
setting. Never introduce:

```text
AH_THERE_IT_IS_CHATGPT_ACCESS_TOKEN=...
```

or any equivalent bearer-token environment variable.

Requirements:

- empty/missing model for `chatgpt-codex` fails clearly;
- credential cache problems fail clearly and without secrets;
- existing heuristic/Gemini/OpenAI-compatible behavior remains unchanged;
- existing config parsing remains deterministic and testable.

### 3. Register only the direct adapter in the provider factory

Extend `build_llm_factory(settings)` with the reviewed direct adapter.

Do not register `codex-exec-experiment`.

Construction must keep provider-specific details behind the existing factory boundary.

`LLMClientInfo` must remain safe and must not contain:

- access token;
- refresh token;
- id token;
- account ID;
- auth file contents.

### 4. Make provider smoke support the direct provider

The existing provider smoke command should exercise the selected direct provider through
the same factory path the application will use.

Requirements:

- ordinary heuristic behavior unchanged;
- `chatgpt-codex` smoke makes a bounded non-tool text request;
- failure messages stay secret-safe;
- smoke does not mutate inventory/production DB;
- live smoke remains manual/operational, not ordinary CI.

### 5. Handle model capability constraints conservatively

0095 found live Codex model metadata that can differ materially by model.

Do not assume every model accepted by the backend has identical tool/request semantics.

For this integration batch:

- preserve the exact request behavior already proven by the reviewed adapter for tested
  models;
- do not broaden support claims to untested `code_mode_only` / Responses Lite models;
- if request fields such as `parallel_tool_calls` require model-specific handling,
  either:
  - derive the safe value from a small explicit provider capability object; or
  - make the option conservative/configurable with a safe default;
- do not add a large hard-coded stale model catalog;
- document exactly which model(s) have live evidence.

If current live probing with `gpt-6-luna` is available, use it as integration evidence
only. This does **not** make it the permanent production model.

### 6. Prove normal application runner integration

Add focused tests that construct the provider through the real factory and exercise it
through the existing chat/runner path using deterministic transport/fakes.

Prove:

- factory returns the direct adapter for the new selector;
- generic runner sees ordinary text/tool calls;
- multi-round tool-result continuation still works;
- provider failure preserves atomic mutation rollback;
- traces store only safe provider/model/config metadata;
- unsupported provider names still fail;
- `codex exec` remains unregistered.

### 7. Preserve credential ownership

Add explicit structural/regression tests proving:

- normal application provider construction never calls an OAuth endpoint;
- no refresh-token field is required or consumed;
- auth cache is not mutated;
- 401/403 does not cause credential refresh;
- replacing the auth cache between calls is observed by the read-only source;
- provider integration does not copy credential material into runtime env or DB.

### 8. Deployment/runbook integration

Update deployment documentation with the post-merge operator configuration needed to use
the direct provider.

Document only variable names and non-secret paths, never credentials.

The intended shape should be approximately:

```text
AH_THERE_IT_IS_LLM_PROVIDER=chatgpt-codex
AH_THERE_IT_IS_LLM_MODEL=<explicit operator-selected model>
[optional safe Codex-home/auth-cache path setting]
```

State clearly:

- Codex/ChatGPT login must already exist for the service user;
- the application does not refresh/login;
- if Codex login expires or disappears, provider calls fail until Codex itself restores
  its credential state;
- public Platform API keys are unrelated to this provider;
- `codex exec` is not involved in normal application runtime.

Do not switch production `runtime.env` in this batch before review/merge.

### 9. Live integration evidence

On U24 as `rdu01`, using the current existing Codex login and without mutating auth
state, run bounded live checks against the direct provider through the normal factory
path.

At minimum:

- one text smoke;
- one native synthetic tool-selection flow;
- one synthetic multi-round continuation.

Use non-sensitive prompts and no production DB mutation.

Record only sanitized results.

If current Codex login is unavailable, deterministic tests may still complete the code
integration, but report the live gate explicitly.

### 10. Keep production activation separate from unreviewed implementation

Do not deploy this work branch as the active production release.

The post-review orchestration step will:

1. merge the reviewed PR;
2. deploy the exact merged main release;
3. activate the already-reviewed trusted-LAN web unit;
4. configure an explicit production provider/model only after operator selection;
5. run production health/provider acceptance.

This separation is intentional.

## Required focused verification

At minimum:

- config tests;
- provider factory tests;
- direct adapter regression tests from 0095;
- credential read-only/redaction tests;
- provider smoke tests;
- runner atomicity/integration tests;
- production provider isolation test showing `codex exec` is still not registered;
- deployment/config documentation assertions where the repository uses structural tests.

Then:

```bash
make compile
git diff --check
```

Because `full_local_required: false`, exact-head Python 3.12 application CI is the
repository-wide regression authority.

Do not turn this batch into 0094 CI scalability work.

## Acceptance

The batch is acceptable when:

- `AH_THERE_IT_IS_LLM_PROVIDER=chatgpt-codex` is a supported normal provider choice;
- model selection remains explicit;
- the direct reviewed adapter is constructed by the production factory;
- `codex exec` remains outside normal factory/runtime;
- no OAuth refresh/login/write code exists;
- secrets/account identity do not leak into metadata/log/errors;
- deterministic factory+runner tests cover text/tools/multi-round/error atomicity;
- bounded live factory-path evidence is green when current login is available;
- docs explain safe post-merge configuration;
- no production release was switched from the unreviewed branch;
- exact-head CI is green.

## Non-goals

- Telegram activation;
- final permanent production model selection;
- model benchmarking;
- app authentication;
- public Internet exposure;
- OAuth refresh/login;
- API-key fallback;
- CI redesign;
- inventory semantics changes.

## Handoff

Stop at:

`READY FOR REVIEW`

Report:

- implementation head SHA;
- provider selector/configuration added;
- live integration evidence and model used;
- focused tests;
- `make compile` / `git diff --check`;
- PR and exact-head CI;
- remaining post-merge activation inputs.

Reviewer is independent under v9 and neither role merges.
