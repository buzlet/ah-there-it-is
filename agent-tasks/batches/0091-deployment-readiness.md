# Batch: 0091-deployment-readiness

Full local required: `false`

## Objective

Bring the actual target host to MVP deployment/environment readiness after the
accepted code-level hardening through 0090.

This batch is operational/deployment work. Preserve accepted product semantics.

## Scope

Prepare and verify the real target installation, including:

- runtime/service-manager arrangement;
- filesystem, environment and secret placement;
- explicit schema/migration readiness;
- application and Telegram process startup/restart behavior;
- operational data/log paths;
- deployment/restart rehearsal;
- backup/restore operational paths where applicable;
- the known Telegram singleton/restart follow-up.

Narrow repository changes to deployment/runtime support, service templates,
runbooks or tests are allowed when real-host evidence demonstrates they are
required for safe deployment.

Never commit secret values, production tokens or private runtime data.

## Work

1. Establish target-host baseline and deployment layout.
   - Inspect the existing checkout/runtime/service state before changing it.
   - Define the minimal durable filesystem layout for application code, venv,
     SQLite data, environment/secrets and logs under the permissions available to
     the deployment user.
   - Keep secrets outside Git and out of command output/review artifacts.
   - Record only reusable non-secret deployment configuration/runbook material in
     the repository.
   - Do not rely on startup auto-migration or auto-repair.

2. Make schema/runtime startup explicit and repeatable.
   - Verify a fresh application environment can be installed from the repository.
   - Verify configuration loading fails closed when required deployment settings
     are absent or malformed.
   - Use the explicit migration/storage CLI path before runtime startup.
   - Verify restart does not implicitly mutate schema or repair application data.
   - Verify web/runtime entrypoints use the intended production database and paths.

3. Establish service-manager behavior.
   - Create or refine the minimal service configuration required for the MVP.
   - Prefer one clearly owned process per runtime responsibility.
   - Ensure restart, stop, start and upgrade procedures are deterministic.
   - Do not introduce a generic orchestration framework.
   - If a required host operation cannot be performed with the permissions
     available to the deployment executor, stop and report the exact prerequisite
     instead of bypassing the executor boundary.

4. Close the Telegram singleton follow-up.
   - Guarantee exactly one Telegram long-polling process can own the production
     bot/database at a time.
   - Intentionally attempt to start a second poller and demonstrate that it is
     rejected or terminated before two instances can concurrently poll/send.
   - Verify normal restart and upgrade cannot overlap old and new pollers.
   - Verify crash/restart timing around:
     - committed inventory mutation before external reply;
     - reply success before durable checkpoint.
   - Preserve application request-key idempotency.
   - A duplicate external reply in the send-succeeded/checkpoint-uncertain window
     may remain an explicitly documented residual risk; duplicate inventory
     mutation must not occur.
   - Do not expose the Telegram token in process lists, logs, tracebacks or
     committed files.
   - Do not send user-visible Telegram test messages unless a real-host acceptance
     step strictly requires it; prefer process/service evidence and controlled
     non-mutating probes.

5. Rehearse deploy/restart/rollback-relevant operations.
   - Exercise install/update, explicit migration, service start, service restart
     and clean stop using the real target paths.
   - Verify stale processes are not left behind.
   - Verify application recovery after an interrupted/restarted runtime.
   - Validate the operational backup path and at least one safe validation or
     restore-rehearsal path against non-production scratch data where practical.
   - Do not destructively overwrite the authoritative production database for a
     rehearsal.

6. Produce durable deployment evidence.
   - Keep reusable service templates/scripts/runbook changes in the repository.
   - Document exact operational commands and expected states without secrets.
   - Separate verified facts from remaining host assumptions.
   - Report any unresolved host prerequisite as `DIRECT FOLLOW-UP: ...`.

## Focused checks

Use the checks appropriate to each changed component. At minimum, for repository
changes run focused tests covering the touched runtime/deployment behavior.

For Telegram singleton/restart work, include a reproducible host-level acceptance
probe that proves a second poller cannot remain active concurrently.

## Final verification

Before handoff:

```bash
make compile
git diff --check
```

Also complete the real-host acceptance sequence:

- explicit schema/migration readiness;
- application startup;
- clean stop/start;
- restart/upgrade overlap rehearsal;
- Telegram second-poller rejection;
- no duplicate inventory mutation across the tested restart windows;
- operational backup/validation or safe restore-rehearsal path;
- secret-leak inspection of generated service/runbook/log evidence.

The final PR head must obtain authoritative Python 3.12 application CI.

## Non-goals / stop conditions

- Do not reopen accepted product semantics.
- Do not add multi-user behavior, new transports or new inventory features.
- Do not redesign the provider/model subsystem.
- Do not add distributed coordination infrastructure merely for future scale.
- Do not commit credentials, tokens, production DB contents or private logs.
- Do not bypass executor identity/permission restrictions.
- Stop and report if safe deployment requires an unavailable privileged host
  operation or a new product/dependency decision.

## Handoff

Implementer stops at:

`READY FOR REVIEW`

Independent review follows `agent-tasks/common/v9.md`.

Neither implementer nor reviewer merges.
