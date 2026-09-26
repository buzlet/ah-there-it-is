# Batch: 0093-production-mvp-activation

Full local required: `false`

## Objective

Move the already code-complete MVP from deployment readiness to an actually usable
production state on the U24 target host, without reopening product semantics.

The primary outcome is a production release based on current `main`, with the real
web runtime healthy and the remaining external activation inputs (live LLM provider
and Telegram credentials) either safely activated and verified or reduced to an
explicit operator-input blocker with no hidden technical work left.

This is the main project stream. Prefer completing launch readiness over unrelated
cleanup, optimization, refactoring, or new features.

## Scope

Allowed scope:

- target-host deployment and release activation as `rdu01`;
- production runtime/environment wiring outside Git;
- deployment/runbook corrections discovered by real activation;
- provider connectivity/smoke verification using already supported provider adapters;
- Telegram Bot API connectivity/readiness using the existing single-user adapter;
- narrow code fixes only when a real launch blocker is reproduced;
- tests/probes/documentation needed for such launch blockers.

The accepted product model, inventory semantics, Telegram semantics, provider-neutral
architecture, and 0091 deployment invariants are not reopened.

Do not place secret values in Git, command lines, PR text, logs intentionally,
screenshots, task files, or shell history.

## Starting state

The code-level MVP and deployment-readiness work are merged.

Current integration main before this issuance contains:

- PR #89 deployment readiness and corrections;
- PR #90 test/CI optimization;
- stable copied user-systemd units;
- production-mode fail-closed preflight;
- production web service previously verified healthy on U24;
- Telegram service installed but intentionally stopped pending real credentials;
- production SQLite currently prepared and empty;
- explicit backup/restore/cross-schema rollback procedures.

The deployment runbook is:

`deploy/README.md`

The application is single-user. Do not add account/role/multi-user infrastructure.

## Work

1. Establish exact target-host launch state
   - Work only through the selected Direct executor as `rdu01`; no `sudo`/`su`.
   - Record current deployed release SHA, `current` symlink target, service states,
     schema revision, DB path, and whether provider/Telegram configuration variables
     are present. Report only presence/absence and safe identities; never print secret
     values.
   - Confirm Telegram is stopped before any release switch.
   - Do not modify production data during discovery.

2. Deploy the accepted current-main release
   - Take and validate a unique pre-deployment backup using the shipped procedure.
   - Prepare a fresh release checkout/venv for the issued/current accepted source.
   - Stop services as required by the runbook.
   - Install stable unit definitions and atomically switch `current`.
   - Run explicit schema upgrade only if needed, then
     `schema-check --require-production`.
   - Start/restart web and verify loopback health.
   - Prove the old release can be removed without invalidating installed unit files.
   - Do not auto-populate the production inventory with demo/test data.

3. Activate the live LLM path if an explicit production provider is already selected
   - Inspect private configuration only for the presence and safe non-secret identity
     of provider/model settings.
   - Do not infer or auto-promote a provider/model merely from historical benchmark
     evidence. Promotion remains an operator decision.
   - If an explicit non-heuristic provider/model and required credential are already
     configured, run the existing provider smoke/contract-safe connectivity path.
   - The smoke must not mutate production inventory.
   - Verify that credential material is not exposed in output/journal/errors.
   - If no explicit live provider/model has been selected, keep the deployment
     otherwise ready and report exactly one operator-input gate naming the required
     non-secret settings. Do not invent a model choice.

4. Activate Telegram if real single-user credentials are already provisioned
   - Check only presence of `AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN` and
     `AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID`; never print values.
   - If both are provisioned, perform a non-mutating real Bot API connectivity check
     using existing application/client behavior and verify readiness semantics.
   - Enable/start the Telegram user unit only after connectivity/configuration gates
     pass.
   - Verify exactly one poller owns both bot identity and production DB ownership.
   - Verify the service reaches ready/active state and does not expose the token.
   - Do not send unsolicited Telegram messages or create inventory records solely for
     the acceptance test.
   - If credentials are absent, leave Telegram disabled/stopped and report that
     external input as the remaining launch gate.

5. Production acceptance snapshot
   - Confirm current release SHA and current symlink agree.
   - Confirm web service is active and `/health` is OK.
   - Confirm schema is current and runtime startup performed no migration/repair.
   - Confirm a validated pre-deployment backup exists.
   - Confirm provider status: active+smoke-green, or explicit external-input blocker.
   - Confirm Telegram status: active+ready, or stopped with explicit external-input
     blocker.
   - Confirm production DB was not populated with synthetic acceptance data.
   - Capture only non-secret evidence needed for independent review.

## Focused verification

Use the shipped probes and the smallest relevant automated tests for any code touched.

At minimum, after any repository change:

```bash
make compile
git diff --check
```

If runtime/deployment code changes, run its focused deployment/config/storage/Telegram
tests and the exact-head authoritative application CI. Do not spend this batch
optimizing CI duration.

## Non-goals / stop conditions

- No new product features.
- No multi-user/auth redesign.
- No QR/barcode/voice/image-recognition work.
- No provider/model auto-promotion.
- No migration of real inventory data unless separately supplied and explicitly in scope.
- No CI/test-runtime optimization except a fix required to unblock authoritative CI.
- No weakening of deployment safety to make activation easier.
- No real secret may be committed or copied into review artifacts.

A missing real provider selection/credential or Telegram credential is an acceptable
external stop condition only after all non-secret technical launch work is complete.
Report it precisely rather than substituting fake credentials.

## Final verification

Before handoff, verify target-host state and, if code changed:

```bash
make compile
git diff --check
```

Obtain exact-head authoritative CI for repository changes.

## Handoff

Implementer stops at:

`READY FOR REVIEW`

Final handoff must include:

- implementation head SHA;
- deployed release SHA and safe target-host service/schema state;
- provider activation status without secrets;
- Telegram activation status without secrets;
- backup/rollback readiness;
- exact verification performed;
- any remaining external operator-input gates.

Reviewer is an independent role. Review the exact implementation head without reading
the implementer's self-review, handoff, conclusions or remaining-risk list.
The reviewer may append correction commits to the same PR/branch only for independently
established findings, according to `agent-tasks/common/v9.md`.

Neither implementer nor reviewer merges.
