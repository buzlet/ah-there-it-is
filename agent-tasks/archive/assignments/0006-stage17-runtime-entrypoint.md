# Assignment 0006: Stage 17 installed-package runtime entrypoint

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage17-runtime-entrypoint`

## Objective

Make the built/installed package directly runnable as the local web application without depending on a source checkout or Justfile, while preserving explicit operator ownership of database migrations. Installed `serve` must be side-effect-light before startup: it validates that the configured database already exists and is at the exact packaged Alembic head, then starts the app; it must never create, migrate, repair, restore, or replace the database automatically.

## Required implementation

1. Add an installed console entry point.
   - Declare a `[project.scripts]` command named `ah-there-it-is` in `pyproject.toml`.
   - Add a small application CLI module with a `serve` subcommand.
   - `serve` accepts explicit `--host` and `--port`; defaults must remain local-only (`127.0.0.1`, port `8000`).
   - Installed/runtime `serve` must not enable Uvicorn reload by default and must not add daemon/system-service behavior.
   - Reuse the existing environment-backed `Settings`/provider configuration instead of inventing a second configuration system.

2. Make application module imports side-effect-light.
   - Remove module-level `app = create_app()` construction from `ah_there_it_is.app`.
   - Keep `create_app()` as the application factory.
   - Update the development `just serve` recipe to use Uvicorn factory mode (`ah_there_it_is.app:create_app`) with reload as the explicit development behavior.
   - Do not make `create_app()` run migrations or mutate the database.

3. Add an explicit read-only runtime schema gate before installed `serve` starts Uvicorn.
   - Compare the configured database's actual Alembic revision/head set with the packaged migration head set.
   - Missing/uninitialized, behind, ahead, or otherwise incompatible schema must fail before the web server starts, with a concise actionable error directing the operator to the existing explicit upgrade command where appropriate.
   - The gate itself must not create a missing SQLite database file merely by checking it.
   - The gate must not call Alembic upgrade/downgrade/autogenerate and must not modify inventory or operational rows.
   - Keep existing migration-check/autogenerate semantics separate from this runtime revision gate.

4. Keep explicit database lifecycle unchanged.
   - Existing `python -m ah_there_it_is.storage_cli upgrade` / `just migrate` remains the explicit upgrade operation.
   - Do not auto-upgrade during `serve`, `create_app()`, module import, bootstrap, portable import to the active database, or HTTP startup.
   - Do not change backup/restore, portable-v1, or bootstrap-v1 semantics.

5. Preserve local-first network behavior.
   - Default bind is loopback only.
   - No TLS, reverse proxy, authentication, public exposure, service manager, Docker/container, or firewall configuration in this stage.
   - `--host` is an explicit operator override; do not silently bind `0.0.0.0`.

6. Add focused runtime tests.
   - CLI argument/default parsing and invalid port/host handling as appropriate.
   - Runtime gate accepts a current migrated database.
   - Runtime gate rejects a missing database without creating it.
   - Runtime gate rejects an unmigrated/old revision and does not mutate it.
   - Importing `ah_there_it_is.app` does not create the default database or instantiate runtime state.
   - Existing direct `create_app()` tests remain supported with injected in-memory session factories.

7. Extend the real wheel smoke test.
   - Prove the wheel contains the console entry-point metadata.
   - Install the wheel outside the source checkout and exercise the installed/runtime CLI path rather than importing source-tree code.
   - Against an explicitly migrated temporary SQLite database, start the installed app on localhost, verify `/health`, the index page, and at least one packaged static asset, then terminate it cleanly.
   - Prove startup from an unrelated working directory and prove a missing/outdated database is rejected before serving.
   - Keep the smoke provider-independent; use the offline heuristic configuration and localhost only.

8. Update user-facing documentation.
   - Document the installed lifecycle explicitly: install wheel -> explicit DB upgrade -> optional bootstrap -> `ah-there-it-is serve`.
   - Keep development `just serve` documented separately from installed/runtime serve.
   - State that installed serve checks schema but never migrates it.
   - Do not mark Stage 17 complete.
   - Do not invent Stage 18. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- No database schema migration for this feature.
- No automatic database creation/migration/repair at runtime.
- No changes to inventory-bootstrap-v1 or inventory-portable-v1.
- No provider/model/network API changes, prompt changes, embeddings, or live-provider verification.
- No systemd/service-manager, Docker/container, TLS, auth, cloud, multi-user, PWA, voice, Telegram, images, QR, or MCP work.
- No dependency, runtime-version, or GitHub Actions version changes unless strictly required by existing installed dependencies; prefer no new dependency.
- No unrelated refactoring.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + self-review + focused verification + canonical verification + PR/CI correction + merge cycle.

Focused verification must include CLI/schema-gate/import-side-effect/wheel-installed HTTP smoke coverage. Then run the complete protocol-v3 canonical verification set on the final implementation and after any task-related correction as required.

Create `agent-tasks/reviews/0006-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
