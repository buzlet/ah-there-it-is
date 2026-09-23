# Assignment 0003: Stage 14 self-contained installed-package migrations

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage14-packaged-migrations`

Assignment 0002 is superseded before execution. This is the active Stage 14 assignment.

## Objective

Remove the source-checkout/current-working-directory dependency from the application's database migration lifecycle so an installed `ah_there_it_is` package can create/upgrade databases and perform portable import using migration resources shipped with the package.

## Required implementation

1. Make Alembic migration resources part of the installed Python package.
   - The runtime must not require repository-root `alembic.ini` or a top-level `migrations/` directory beside the current working directory.
   - Keep the existing migration history and revision IDs unchanged.
   - Do not generate a new schema migration merely for relocating migration resources.

2. Introduce one small internal migration configuration/runner boundary used by runtime code.
   - Construct Alembic configuration programmatically from packaged resources plus an explicit database URL.
   - An explicit target URL must remain immune to ambient `AH_THERE_IT_IS_DATABASE_URL`.
   - Avoid duplicate migration-configuration logic in storage/import code.

3. Update portable import to use the packaged migration boundary.
   - `import_portable_inventory(...)` must work from an arbitrary current working directory with no repository `alembic.ini`.
   - Preserve every Stage 11-13 safety invariant: validate before output creation, new target only, no overwrite/merge, stable IDs/timestamps, current normalization/FTS reconstruction, old portable source revision as metadata only.

4. Provide an explicit programmatic database-upgrade operation using the same packaged migration boundary.
   - Upgrade to the current head.
   - Do not auto-migrate from `create_app()`, module import, or server startup.
   - Explicit operator action remains required for schema mutation.

5. Expose the explicit upgrade through the existing command-line/Just workflow with the smallest coherent surface.
   - Keep `Justfile` canonical for source-checkout development.
   - Do not introduce a new CLI framework dependency.

6. Add tests proving source-checkout/current-working-directory independence.
   - Run migration and portable-import behavior after changing to an unrelated temporary directory.
   - Prove a fresh database reaches `CURRENT_SCHEMA_REVISION`.
   - Prove the committed `inventory-portable-v1` fixture still imports and searches correctly through the packaged migration path.
   - Keep existing migration upgrade/downgrade/autogenerate tests meaningful; adapt shared configuration helpers rather than preserving repository-root assumptions.

7. Prove distribution completeness with a real wheel smoke test.
   - The U24 project venv is prepared with pip 25.1.1, setuptools 82.0.1, wheel 0.46.3, and no `build` package, matching the internal sandbox toolchain relevant to wheel construction.
   - Build the project wheel without adding dependencies, using the available setuptools/wheel path; `python -m pip wheel --no-build-isolation --no-deps .` is known to work in this environment.
   - Inspect or install the built wheel in temporary isolation and prove the Alembic migration environment and all revision files needed at runtime are actually present in the wheel/installed package.
   - Execute the fresh-database upgrade and portable-v1 import/search smoke path from outside the source tree while importing `ah_there_it_is` from the wheel installation, not from the checkout.
   - Assert the imported package path/resource path is outside the repository so an editable/source-tree fallback cannot make the test pass accidentally.

8. Keep package/runtime versions aligned with the active sandbox.
   - No dependency upgrades.
   - No GitHub Actions/runtime updates merely for deprecation warnings.
   - Use existing Alembic/setuptools/importlib facilities unless functionality truly requires otherwise.

9. Update documentation only for the installed-package migration/upgrade behavior.
   - Do not mark Stage 14 complete in product stage planning; final stage transition remains an orchestrator decision after receiving your merged-result summary.
   - Do not invent Stage 15.

## Non-goals

- No automatic migration during application startup.
- No database merge mode.
- No change to portable v1 semantics.
- No provider/model, prompt, voice, Telegram, image, QR, MCP, PWA, cloud, embeddings, or multi-user work.
- No unrelated packaging redesign or dependency cleanup.
- No GitHub Actions version changes.

## Verification and delivery

Follow `agent-tasks/common/v3.md` completely.

In addition to the normal focused/canonical verification, the wheel smoke test in item 7 is mandatory.

Own the full implementation -> self-review -> verification -> PR -> CI/fix loop -> merge cycle. Stop only after the PR is merged and local `main` is clean/synchronized, or earlier if a genuine architecture/product/infrastructure blocker requires an orchestrator decision.
