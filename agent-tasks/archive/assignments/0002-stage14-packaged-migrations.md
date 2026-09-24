# Assignment 0002: Stage 14 self-contained installed-package migrations

Protocol: `agent-tasks/common/v2.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage14-packaged-migrations`

## Objective

Remove the source-checkout/current-working-directory dependency from the application's database migration lifecycle so an installed `ah_there_it_is` package can create/upgrade databases and perform portable import using migration resources shipped with the package.

## Required implementation

1. Make Alembic migration resources part of the installed Python package.
   - The runtime must not require repository-root `alembic.ini` or a top-level `migrations/` directory to exist beside the current working directory.
   - Keep the existing migration history and revision IDs unchanged.
   - Do not generate a new schema migration merely for relocating migration resources.

2. Introduce one small internal migration configuration/runner boundary used by runtime code.
   - It must construct Alembic configuration programmatically from packaged resources plus an explicit database URL.
   - It must remain immune to an ambient `AH_THERE_IT_IS_DATABASE_URL` when the caller supplies an explicit target URL.
   - Avoid duplicate migration-configuration logic in storage/import code.

3. Update portable import to use the packaged migration boundary.
   - `import_portable_inventory(...)` must work from an arbitrary current working directory with no repository `alembic.ini`.
   - Preserve every Stage 11-13 safety invariant: validate before output creation, new target only, no overwrite/merge, stable IDs/timestamps, current normalization/FTS reconstruction, old portable source revision as metadata only.

4. Provide an explicit programmatic database-upgrade operation for the application database using the same packaged migration boundary.
   - Upgrade to the current head.
   - Do not auto-migrate from `create_app()`, module import, or server startup.
   - Explicit operator action remains required for schema mutation.

5. Expose the explicit upgrade through the existing command-line/Just workflow with the smallest coherent surface.
   - Keep `Justfile` canonical for source-checkout development.
   - Do not introduce a new CLI framework dependency.

6. Add tests that prove source-checkout independence.
   - Run migration/portable-import behavior after changing the process current working directory to an unrelated temporary directory.
   - Prove a fresh database reaches `CURRENT_SCHEMA_REVISION`.
   - Prove the committed `inventory-portable-v1` compatibility fixture can still import and search correctly through the packaged migration path.
   - Keep existing migration upgrade/downgrade/autogenerate tests meaningful; adapt their configuration helper rather than duplicating repository-root assumptions where practical.

7. Keep package/runtime versions aligned with the active sandbox.
   - No dependency upgrades.
   - No GitHub Actions/runtime version updates merely for deprecation warnings.
   - Use existing Alembic/setuptools/importlib facilities unless functionality truly requires otherwise.

8. Update documentation only for the new installed-package migration/upgrade behavior.
   - Do not mark Stage 14 complete.
   - Do not invent Stage 15; stage finalization remains the orchestrator's job after PR verification.

## Non-goals

- No automatic migration during application startup.
- No database merge mode.
- No change to portable v1 semantics.
- No provider/model, prompt, voice, Telegram, image, QR, MCP, PWA, cloud, embeddings, or multi-user work.
- No unrelated packaging redesign or dependency cleanup.
- No GitHub Actions version changes.

## Delivery

Commit, push, and open a PR to `main`. Stop after opening the PR.
