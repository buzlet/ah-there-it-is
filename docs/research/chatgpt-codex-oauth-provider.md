# ChatGPT/Codex OAuth provider spike

Observed 2026-09-26 with Codex CLI 0.156.1. This note records sanitized research and
bounded experiments for batch 0095. No credential values, account identifiers, or live
response bodies are retained here.

## Decision

Carry the direct ChatGPT/Codex Responses adapter forward as the preferred candidate for a
later, explicitly approved integration batch. On the current ChatGPT login it passed
text generation, native structured tool selection, and a synthetic tool-result
continuation. It re-reads the existing Codex credential cache and has no login, refresh,
or credential-write path.

Keep the adapter isolated until a later batch decides how application configuration
selects the ChatGPT login and model. Before enabling it, integration must account for
model-specific Codex catalog behavior, particularly models marked `code_mode_only` and
`use_responses_lite`. No production provider or model is selected by this spike.

The public OpenAI Responses endpoint is not a fallback for this OAuth credential: the
same current ChatGPT access credential received HTTP 401 there with the missing Platform
scope `api.responses.write`, while the ChatGPT/Codex endpoint accepted it. Do not route
failed Codex calls to an API-key endpoint or an unrelated `OPENAI_API_KEY`.

The `codex exec` adapter is a useful compatibility reference and manual fallback
experiment, but it is not the preferred app runtime path. Each call starts a new Codex
process, and the CLI owns its normal authentication lifecycle (which may update its own
credential cache). Its structured-output instruction also emulates application tools;
the subprocess must detect and kill unexpected internal tool activity.

## Existing application boundary

`agent.protocol.LLMClient` accepts the complete `AgentMessage` history and tool
definitions and returns generic text and `ToolCall` values. `AgentRunner` owns the
conversation loop, calls application tools, appends tool results, and records traces.
The new direct and subprocess clients implement that interface without changing the
runner, inventory semantics, or production factory. Neither experimental provider is
registered in `agent/factory.py`; production remains on its existing heuristic provider.

The standalone live probe uses synthetic prompts and an in-memory message list. It does
not connect to the application database, Web server, or Telegram. Ordinary tests use
fake transport/processes and do not contact OpenAI.

## Credential and endpoint evidence

The installed CLI reported ChatGPT authentication and used a file-backed Codex cache.
The auth cache was inspected without printing its contents; its state was not changed by
the direct probes. The application credential source reads only the access token and
optional account ID on each request. It does not read or use a refresh token, contact an
OAuth token endpoint, or write/chmod/copy/rotate the cache. A 401/403 fails without
retrying authentication. Authentication values are excluded from adapter metadata and
redacted from upstream error details.

The A/B probe sent the same current access credential only to these two explicit
endpoints:

| Endpoint | Result |
| --- | --- |
| `https://api.openai.com/v1/responses` | HTTP 401; credential not accepted for Platform Responses; sanitized error identified missing `api.responses.write` scope |
| `https://chatgpt.com/backend-api/codex/responses` | HTTP 200; streamed response completed with nonempty text |

A further bounded request to the ChatGPT/Codex endpoint without the account identity
header also returned a completed response. The adapter sends `ChatGPT-Account-ID` only
when the current credential source provides it. This is an observation for the tested
login and date, not a promise about future backend requirements.

OpenAI documents the distinction between ChatGPT sign-in and API-key access in its
[Codex authentication guide](https://developers.openai.com/codex/auth). OpenAI's
[Codex agent loop overview](https://openai.com/index/unrolling-the-codex-agent-loop/)
describes the ChatGPT-authenticated Codex endpoint separately from the public Platform
Responses endpoint. The pinned Codex 0.156.1 source was also inspected for request
construction, bearer/account headers, originator, model catalog, and JSONL events:
[request configuration](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/core/src/client.rs),
[bearer auth](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/model-provider/src/bearer_auth_provider.rs),
[default client headers](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/login/src/auth/default_client.rs),
[model endpoint](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/codex-api/src/endpoint/models.rs), and
[exec JSONL events](https://github.com/openai/codex/blob/rust-v0.156.1/codex-rs/exec/src/exec_events.rs).
The [Codex CLI reference](https://developers.openai.com/codex/cli/reference) documents
`codex exec`, its JSONL output, sandbox controls, and ephemeral session option.

Three public implementations were reviewed:

1. [Simon Willison's `llm-openai-via-codex`](https://github.com/simonw/llm-openai-via-codex/blob/main/llm_openai_via_codex.py)
   reads Codex auth state, requests the ChatGPT/Codex endpoint with Responses streaming,
   and maps function calls/results. Its implementation also refreshes and writes the
   cache when needed; this spike intentionally does not copy that behavior.
2. [OpenCode's Codex OAuth provider](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/plugin/openai/codex.ts)
   uses OpenCode's own OAuth and auth store, the ChatGPT/Codex endpoint, and an optional
   account header. It is a provider integration reference, but does not simply reuse the
   Codex CLI cache.
3. [The `codex-proxy` project](https://github.com/thezillo/codex-proxy) provides a local
   OpenAI-compatible proxy around Codex auth and translates chat-completion requests.
   It handles token rotation and warns about concurrent processes sharing auth state;
   those proxy and refresh responsibilities are out of scope here.

## Direct adapter

`ChatGPTCodexLLMClient` sends a bounded streaming Responses request to the fixed
ChatGPT/Codex endpoint. It sets `store: false`, streams SSE, supplies the Codex originator
and user agent, and includes the account header when present. It reconstructs the request
from the complete caller-provided history, maps native function calls and results, and
returns generic `LLMResponse`/`ToolCall` objects. It keeps no remote conversation state.

The implementation bounds response and error bodies, disables redirects and ambient
proxy environment settings, retries only bounded transient failures, and does not retry
authentication errors. Unknown tool names and malformed/incomplete stream output fail
closed. The parser handles fragmented SSE events and uses emitted function-call events
when the completed response has an empty output array, a behavior observed in the live
tool-selection response.

## Codex model catalog

A live request to the Codex model catalog returned HTTP 200 and nine models. The selected
`gpt-6-luna` was available and was used for all live scenarios. The catalog marked these
other models as code-mode-only and Responses Lite:

| Model | Catalog tool mode | Responses Lite | Catalog API support |
| --- | --- | --- | --- |
| `gpt-5.6-sol` | `code_mode_only` | yes | yes |
| `gpt-5.6-terra` | `code_mode_only` | yes | yes |
| `gpt-5.6-luna` | `code_mode_only` | yes | yes |

Codex source disables parallel tool calls for Responses Lite models. The experimental
direct adapter currently sends `parallel_tool_calls: true` and does not yet fetch model
metadata, so this spike makes no compatibility claim for those GPT-5.6 models. Later
integration should consume the current catalog or require an explicit supported model,
and derive request options from the selected model's metadata before enabling any
model.

## Subprocess adapter

`CodexExecLLMClient` invokes the installed CLI with `--ephemeral --json`, a read-only
sandbox, an empty temporary working directory, and a strict output schema. Its child
environment is allowlisted and excludes application database, Telegram, provider, and
API-key settings. It supplies the complete conversation as prompt data and translates
the final structured JSON into generic tool calls. The application runner still executes
those tools in its own process.

The adapter rejects unknown JSONL events/items and kills the process group if Codex
starts an internal tool event, times out, or exceeds output bounds. Tests exercise
process cleanup including a spawned child. `--ephemeral` prevents session rollout files,
but Codex itself remains responsible for its auth and may update its own cache under its
normal CLI behavior. This is why the direct provider is preferred when the later app
integration requires the application to remain strictly read-only with respect to Codex
auth state.

## Live scenario results

All scenarios below used model `gpt-6-luna` and non-sensitive synthetic prompts. Each
provider passed text, tool selection, and a two-round synthetic tool-result continuation.
The tool path selected `lookup_item`; the continuation used a fake result for a synthetic
item and returned its location. The subprocess reported zero internal tool events for
all successful scenarios. No result was written to the production database.

The direct adapter reused an HTTP client for each repeated probe. `codex exec` started a
new process per model call. These small samples are compatibility evidence, not a
statistical performance claim.

| Scenario | Direct results (seconds) | Direct median | `codex exec` results (seconds) | CLI median |
| --- | --- | ---: | --- | ---: |
| Text, 3 repeats | 1.049776, 1.322454, 1.687465 | 1.322454 | 4.271460, 4.387633, 4.738026 | 4.387633 |
| Tool selection, 3 repeats | 4.067528, 1.693457, 10.518345 | 4.067528 | 7.763215, 4.018112, 4.266921 | 4.266921 |
| Multi-round, 3 observations | 7.669443, 5.268171, 3.304305 | 5.268171 | 10.186161, 8.957229, 10.213184 | 10.186161 |
| No tool selected, one probe | 1.325088 | — | 6.925306 | — |

The CLI subprocess itself started in roughly 0.0004–0.0010 seconds in these samples;
first stdout bytes arrived in roughly 0.35–0.54 seconds. CLI JSON output included thread
events before the final structured model message, so first-byte time is not the time to
a usable answer. The direct path had fewer process layers and was faster in these text
samples; tool and multi-round latencies varied substantially on both paths.

## LAN deployment result

The shipped stable web unit now explicitly runs
`ah-there-it-is serve --host 0.0.0.0 --port 8000 --allow-nonlocal`. Its installer validates the explicit bind, acknowledgement, and
Telegram environment isolation. Deployment docs describe access from a trusted private
development network and state that the app has no authentication.

Focused deployment tests confirm the loopback-safe CLI default and validate the shipped
unit and installer. A temporary scratch listener bound to `0.0.0.0` returned HTTP 200
for health checks through both `127.0.0.1` and the host LAN address `192.168.1.190`; it
was terminated afterward. The already-installed host service was not switched or
restarted as part of this spike, so the shipped unit is prepared for LAN use but the
production service has not been activated on the LAN.

## Verification and follow-up

Focused tests cover credential-source read-only behavior and errors, direct request and
SSE mapping, tool/multi-round history, redaction, subprocess argv/environment, structured
output, timeouts and process-group cleanup, unexpected internal tools, runner
compatibility, provider isolation, deployment safeguards, and runtime CLI behavior.
Live probes are manual and are not part of ordinary CI.

The later integration batch should decide how ChatGPT auth is selected, read model
catalog metadata or constrain model selection, adapt request parameters to model
capabilities, and add explicit production configuration only after those decisions.
Production service activation, any application authentication policy, and Telegram
configuration remain separate choices. This batch does not choose a permanent model or
enable either experimental provider.
