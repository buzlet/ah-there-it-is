# Assignment 0017: persisted trace/config privacy hardening

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/hardening-trace-config-privacy`

## Objective

Prevent arbitrary provider configuration values from being copied into new persisted run metadata while preserving useful stable evaluation grouping and compatibility with existing logs.

This is a maintenance assignment and does not consume/redefine product Stage 26.

## Required behavior

- Make the `LLMClientInfo.config` persistence contract explicitly safe: values placed there must be intentional non-secret evaluation metadata, not a copy of arbitrary request configuration.
- For OpenAI-compatible and Gemini adapters:
  - preserve stable non-secret operational fields already useful for evaluation (for example timeout/retry/temperature/transport as applicable);
  - never persist API keys;
  - sanitize persisted base URLs so credentials/userinfo, query and fragment cannot leak;
  - do **not** persist raw `extra_body` values;
  - when extra body is present, persist at most a structural indicator such as sorted top-level key names, without nested values or a value-derived fingerprint.
- Request behavior must remain unchanged: the full configured `extra_body` still goes to the provider exactly as before subject to existing protected-field rules.
- Existing historical `AgentRunLog.llm_config` rows remain readable; do not rewrite/delete/redact old rows in this assignment.
- Evaluation summary/grouping must continue to work with both old and new config shapes. New safe config should remain deterministic so equal safe metadata groups together.
- Replay/experiment/evaluation pages must not require the removed raw values.
- Add tests with malicious-looking URL userinfo/query and nested `extra_body` secrets proving the secret values do not appear in newly persisted `llm_config`, rendered evaluation data or serialized run metadata.
- Keep provider/model identity fields and prompt hashes unchanged.

## Constraints

No automatic trace deletion/retention scheduler, no migration of old traces, no authentication system, no provider request behavior changes, no new secrets store, no dependency/runtime/workflow upgrades or unrelated refactoring.

## Focused verification

Run focused adapter/evaluation/run-log/UI serialization tests plus provider-contract checks, then the canonical v4 verification set.
