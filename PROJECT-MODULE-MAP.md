# Project module map

## Main application layers

- `src/ah_there_it_is/app.py` — FastAPI factory.
- `config.py`, `data_paths.py`, `runtime_cli.py` — settings, stable data paths and installed runtime.
- `db/` — SQLAlchemy models/session, FTS and packaged migrations.
- `domain/` — normalization, controlled states and typed search primitives.
- `services/inventory.py` — central transactional write boundary.
- `services/search.py` — deterministic bounded retrieval.
- `services/location_suggestions.py` — evidence-based location suggestions.
- `services/catalog.py`, `activity.py` — browser/read projections.
- `services/conversations.py`, `chat_requests.py` — bounded conversation context and crash-safe request coordination.
- `services/chat_application.py` — shared Web/adapter chat execution and source identity boundary.
- `agent/protocol.py` — provider-neutral LLM/tool types.
- `agent/runner.py` — atomic bounded agent loop.
- `agent/tools.py`, `schemas.py`, `write_resolution.py` — safe tool surface and write authorization.
- `agent/openai_compatible.py`, `gemini.py` — provider adapters.
- `agent/scenario_mock.py`, `fakes.py`, `heuristic.py` — deterministic/offline model doubles.
- `storage.py`, `storage_cli.py`, `bootstrap.py`, `database_doctor.py` — storage, recovery, onboarding and diagnostics.
- `web/` — routes, schemas, templates and static browser assets.
- `telegram/` — token-safe Bot API transport, single-user private-text adapter, durable polling and explicit runtime.
- `db/models.py` `ItemMedia` — ordered external photo references; Telegram chat bindings/checkpoint state stay adapter-local.
- evaluation modules — deterministic scenario/retrieval/provider research pipelines.

## Process tooling

- `tools/agent/lifecycle_checkpoints.py` — control/seed/checkpoint inspection.
- `tools/agent/canonical_verifier.py` — optional full-local high-risk batch verifier.
- `tools/agent/ci_waiter.py` — bounded final PR CI observation.
- `tools/agent/process_state.py` — shared POSIX process-state helper.

Historical process docs are archived and are not part of this map.
