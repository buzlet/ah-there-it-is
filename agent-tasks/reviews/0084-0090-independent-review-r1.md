# Independent adversarial review 0084–0090 (findings frozen before comparison)

Target: `b7fce1be9ef24b2b8b92e8cfb93d1dba5e5e9dd6`. Control: `898e2dd7cf99e691a8cc8dc7de4bcf9e936585d7`. Protocol: v8. Decision: **corrections required**.

I read the immutable manifest and seven control task specs, accepted quantity/Undo/media/product decisions, then independently traced Web and Telegram through the shared chat service, keyed reservation and AgentRunner, plus inventory split/media/Undo, catalog and history bounds, doctor, runtime CLI/schema gate, package migration resources and promotion hard gates. The implementation report and PR #87 were not read before this decision.

Confirmed on I by failing adversarial regressions:

1. A configured API key also present in the provider base URL path is persisted in `LLMClientInfo.config.base_url` for OpenAI-compatible and Gemini clients. `test_provider_trace_url_does_not_persist_configured_key_in_path` fails.
2. The OpenAI-compatible transport sanitizes the top-level `ProviderRequestError`, but `raise ... from exc` retains a secret-bearing cause in a normal formatted traceback. `test_provider_request_error_traceback_does_not_expose_key` fails.
3. A malformed provider `content` containing an echoed configured key raises raw Pydantic `ValidationError`; both `AgentRunLog.error` and `ChatRequestRecord.error` persist the key. `test_malformed_provider_response_cannot_persist_echoed_key` fails.
4. `2**63` quantity and media position pass Web/Agent schema validation and hit SQLite conversion, producing HTTP 500 instead of a stable client error. The same test later exposed an oversized path Item ID causing HTTP 500, and the page input has the same unbounded offset risk. Direct inventory quantity raises `OverflowError`. `test_oversized_inventory_numbers_rejected_before_sqlite` and direct domain/media regressions cover these boundaries.

Adversarial areas checked without a further confirmed application defect: failed first keyed turn retains only its audit anchor/failed run/failed request; same-key race, uncertain final commit and response-loss replay; Telegram send/checkpoint ordering and duplicate IDs; split media ownership and compensation order; catalog/media eager loading, message/request/event windows and doctor samples; CLI read-only schema gate and migration packaging; promotion evidence completeness gate. Existing focused tests passed before corrections. No deployment-host configuration was changed.

DIRECT FOLLOW-UP: On the actual target host, guarantee a single Telegram long-polling process per bot/database and rehearse restart after a committed chat mutation but before reply/checkpoint; verify the durable request key prevents a second inventory effect. The application has no cross-process polling lease by design.

## Post-freeze comparison

Only after recording the independent correction decision above, I read the implementation self-review and PR #87 body. The implementation documented strict integer rejection of booleans and redaction of configured secrets from top-level provider error text. It did not test the configured key in the trace URL path, secret-bearing exception causes, malformed provider response errors persisted to the failed run/request, or SQLite-range overflow. Its declared Group B was run in complete shards in the sandbox; the direct-shell review ran the full group as one command. The comparison yielded no additional defect to reproduce and did not change the independent findings. The target-host Telegram singleton follow-up agrees with the implementation report.

## Corrections and verification

- Redact known configured secrets from persisted provider base-URL metadata and suppress secret-bearing transport causes in ordinary tracebacks for both OpenAI-compatible and Gemini adapters.
- Convert malformed OpenAI-compatible response validation failures into a generic `ProviderProtocolError`, so failed-run/request records do not persist echoed response values.
- Limit persisted integer values to SQLite's signed 64-bit range at Web/Agent schemas and inventory quantity/media services; bound route path IDs and paged offsets before SQL. Existing 400 responses for invalid low page/cursor values are preserved.
- The four new adversarial regressions failed on I; a fifth path-ID assertion failed before its correction. Direct quantity/media boundary tests and a Gemini traceback test cover adjacent paths.

Final direct-shell verification after corrections: Group A, Group B, and Group C exact declared test-file unions green; `make provider-contract` (23 passed), `make migration-check`, `make corpus-check` (71 cases), `make scenario-check` (71 scenarios), `make scenario-eval` (71 completed; 0 failed), `make retrieval-eval` (86 passed), `make compile`, and `git diff --check` green. No live provider or Telegram call was made.

Remaining code-level risk: the accepted Telegram at-least-once reply policy permits a duplicate outbound reply after a send/checkpoint uncertainty; keyed chat replay prevents duplicate inventory mutation. Failed first turns retain a non-user-visible empty Conversation audit anchor. Deployment readiness awaits the separate target-host Direct batch and its singleton rehearsal.
