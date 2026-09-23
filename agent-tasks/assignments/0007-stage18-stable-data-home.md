# Assignment 0007: Stage 18 stable local data home

Protocol: `agent-tasks/common/v3.md`

Repository: `buzlet/ah-there-it-is`
Branch: `feat/stage18-stable-data-home`

## Objective

Make installed local operation independent of the process current working directory by giving the application one deterministic per-user data directory and using it for the default SQLite database. Preserve explicit database URL override semantics and side-effect-light configuration: merely importing modules, resolving settings, showing paths, or running the serve schema gate must never create directories or database files.

## Required implementation

1. Add a small stdlib-only application data-path resolver.
   - No new dependency such as `platformdirs` in this stage.
   - Default per-user data directory:
     - Linux/other Unix: `$XDG_DATA_HOME/ah-there-it-is` when `XDG_DATA_HOME` is non-blank, otherwise `~/.local/share/ah-there-it-is`.
     - macOS: `~/Library/Application Support/AhThereItIs`.
     - Windows: `%LOCALAPPDATA%\\AhThereItIs`; if `LOCALAPPDATA` is unavailable, use a deterministic per-user fallback under the home directory rather than the current working directory.
   - Add `AH_THERE_IT_IS_DATA_DIR` as an explicit data-directory override. Expand `~` and resolve the chosen data directory to an absolute path.
   - Resolving the path must not create it.

2. Make the default database CWD-independent.
   - When `AH_THERE_IT_IS_DATABASE_URL` is set and non-blank, preserve it exactly as the highest-precedence database configuration.
   - Otherwise derive the SQLite database URL from `<resolved data dir>/inventory.db`.
   - `AH_THERE_IT_IS_DATA_DIR` affects only this default path; it must not rewrite an explicit `AH_THERE_IT_IS_DATABASE_URL`.
   - Direct/default `Settings` construction and `get_settings()` must remain deterministic and testable; do not add hidden CWD dependence.

3. Keep configuration and runtime reads side-effect-free.
   - `get_settings()`, application import, `create_app()`, runtime schema gate, and any read-only path/status command must not create the data directory or database.
   - Installed `serve` still rejects a missing database exactly as Stage 17 requires.
   - Do not add automatic migration or first-run database creation to `serve`.

4. Make the existing explicit upgrade path capable of initializing the stable default location.
   - For a file-backed SQLite target, the explicit `python -m ah_there_it_is.storage_cli upgrade` operation may create the database parent directory before Alembic writes the database.
   - Directory creation belongs to that explicit write operation, not generic settings/path resolution.
   - Preserve explicit URL override behavior, including absolute user-supplied SQLite locations.
   - Do not change Alembic revision history or startup migration policy.

5. Add a read-only installed CLI path/status surface.
   - Add `ah-there-it-is paths` (or an equivalently narrow name) that reports the resolved application data directory and effective SQLite database path without creating either.
   - Output must be concise and machine-readable (JSON is preferred).
   - Do not print provider API keys or other secrets.
   - If an explicit database URL is not a supported file-backed SQLite URL, report the data directory plus a safe indication that the database is explicitly configured; do not echo credentials.

6. Prove CWD independence.
   - Under a controlled per-user environment, resolve settings from two unrelated working directories and obtain the same absolute default database path.
   - Run explicit upgrade from one directory and installed `serve` from another; both must address the same database without setting `AH_THERE_IT_IS_DATABASE_URL`.
   - Verify no stray `ah_there_it_is.db`, `inventory.db`, WAL, or SHM file appears in either working directory.

7. Extend focused and wheel-installed coverage.
   - Linux XDG default and fallback behavior.
   - Windows/macOS path resolver behavior through deterministic unit tests without requiring those operating systems.
   - `AH_THERE_IT_IS_DATA_DIR` override and explicit `AH_THERE_IT_IS_DATABASE_URL` precedence.
   - Blank override handling must be explicit and consistent; do not treat whitespace as a filesystem path.
   - Settings/path resolution creates no directories.
   - Explicit upgrade creates the missing data-directory parent and current-schema database.
   - `paths` is read-only.
   - Extend the real wheel smoke so a wheel installed outside checkout can upgrade and serve the same default DB from different CWDs with a controlled data-home environment.

8. Update installed lifecycle documentation.
   - Default installed use should no longer require exporting `AH_THERE_IT_IS_DATABASE_URL`.
   - Document the resolved per-platform data location and `AH_THERE_IT_IS_DATA_DIR` / `AH_THERE_IT_IS_DATABASE_URL` precedence.
   - Keep explicit upgrade -> optional bootstrap -> serve ordering.
   - Keep explicit database URL examples for advanced/custom placement.
   - Do not mark Stage 18 complete.
   - Do not invent Stage 19. Stage transition remains the orchestrator's responsibility after the merged assignment is reviewed.

## Constraints

- No database schema migration.
- No automatic migration/database creation during import, settings resolution, `create_app()`, or `serve`.
- No config-file persistence, keyring, secret storage, registry writes, or environment mutation.
- No new dependency solely for platform path handling.
- No changes to inventory-bootstrap-v1, inventory-portable-v1, backup/restore semantics, prompts, providers/models, or application scenarios unless a test reference must be adjusted for the new default path.
- No systemd/service-manager, Docker/container, installer packaging, TLS, auth, cloud, multi-user, PWA, voice, Telegram, images, QR, or MCP work.
- No dependency/runtime/GitHub Actions upgrades and no unrelated refactoring.

## Verification and delivery

Follow `agent-tasks/common/v3.md` for the full implementation + self-review + focused verification + canonical verification + PR/CI correction + merge cycle.

Focused verification must include data-path/config precedence, side-effect-free resolution, explicit-upgrade directory creation, CWD independence, installed `paths`, and real-wheel cross-CWD serve coverage. Then run the complete protocol-v3 canonical verification set on the final implementation and after any task-related correction as required.

Create `agent-tasks/reviews/0007-r1.md`, merge only after required CI is green, synchronize local `main`, and return the compact protocol-v3 summary.
