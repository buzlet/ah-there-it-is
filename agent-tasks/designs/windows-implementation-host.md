# Windows 11 implementation-host assessment

Status: assessment only; no runtime/process changes implemented.

## Conclusion

The **application itself is substantially Windows-capable**, but the current implementation-agent lifecycle is **not Windows-capable as issued**.

A Windows 11 implementation host is feasible with a small portability/process stage. It is not a rewrite of the application.

## Hard blocker 1: protocol pins U24

Both current execution protocols explicitly require:

- Remote Commander;
- U24;
- device `u24-gpt`;
- stop if that device is unavailable.

Therefore a compliant v4/v5 implementation agent must currently refuse to move execution to Windows even if the repository is available there.

A future host-neutral protocol must identify an approved execution target supplied by the manifest/launcher, rather than hard-code `u24-gpt`.

## Hard blocker 2: canonical Just recipes contain POSIX shell syntax

Current `Justfile` includes:

```text
rm -f /tmp/ah-there-it-is-migration-check.db
AH_THERE_IT_IS_DATABASE_URL=sqlite:////tmp/... python ...
```

and retrieval evaluation defaults to a `/tmp/...` output path.

These assumptions are not portable to native PowerShell/cmd on Windows.

Because v4/v5 require the canonical Just verification set, this is a lifecycle blocker, not merely a developer inconvenience.

### Recommended fix

Move temporary-path and temporary-database setup into Python entry points/helpers using `tempfile` / `pathlib`.

Keep Just recipes as thin platform-neutral invocations, for example:

```text
migration-check:
    python -m ah_there_it_is.dev_checks migration-check

retrieval-eval:
    python -m ah_there_it_is.retrieval_eval ...
```

Do not maintain separate Bash and PowerShell copies of the same verification logic.

## Hard blocker 3: installed-wheel test assumes Unix prefix layout

`tests/test_wheel_migrations.py` currently assumes pip `--prefix` produces:

- `lib/python*/site-packages/...`
- `bin/ah-there-it-is`

That is a Unix installation layout.

The same test also builds its isolated runtime environment around Unix-style `HOME` / `XDG_DATA_HOME`.

Since this file is part of ordinary `pytest`, `just check` cannot be expected to pass natively on Windows.

### Recommended fix

Make the packaging test discover the installed distribution instead of assuming prefix paths.

Preferred options:

1. create a temporary venv with Python's `venv` module;
2. locate its interpreter using platform-aware helpers:
   - POSIX: `bin/python`;
   - Windows: `Scripts/python.exe`;
3. install the wheel into that venv;
4. query the interpreter for the installed package/resource path and console entry point behavior;
5. test Windows data-home behavior using `LOCALAPPDATA` where the runtime is Windows.

This tests the actual supported installation model and avoids reproducing pip's platform-specific directory rules in tests.

## Protocol shell snippets

v4 contains POSIX-specific verification such as:

```sh
test "$base_main_sha" = "$(git rev-parse origin/main)"
```

Git operations themselves are cross-platform, but the shell snippet is not PowerShell syntax.

A host-neutral protocol should express checks semantically, with approved Bash and PowerShell forms or, preferably, a tiny repository Python helper for lifecycle assertions.

## Temporary artifact policy

The protocols currently say to use `/tmp`.

For a Windows-capable host, the rule should become:

> use the operating system temporary directory for disposable verification artifacts; do not place persistent notes there.

Implementation should use Python `tempfile.gettempdir()` / `TemporaryDirectory` rather than embedding an OS path.

## Application/runtime portability already present

The repository already has useful Windows support:

- `pathlib` is used broadly for filesystem handling;
- `resolve_data_dir()` has explicit Windows handling;
- `LOCALAPPDATA` is used when present;
- fallback is `%USERPROFILE%\AppData\Local\AhThereItIs` semantics;
- Windows path resolution has unit coverage;
- SQLite/file-backed storage code is largely platform-neutral;
- FastAPI/Uvicorn/provider adapters are not Linux-specific;
- `pyproject.toml` declares Python `>=3.12` without OS restriction.

Therefore the application should not need an architecture change merely to develop it on Windows.

## Areas that should receive native-Windows verification

Before declaring Windows an approved implementation host, run the complete canonical suite natively and pay particular attention to:

- SQLite WAL/SHM cleanup and file replacement;
- restore/backup rehearsal while handles are open;
- `os.replace` behavior;
- temporary files and sidecar deletion;
- packaged Alembic migrations;
- installed console script;
- default `LOCALAPPDATA` data home;
- non-loopback serve guard;
- subprocess lifecycle/termination in installed-wheel tests.

Windows file-locking semantics are stricter than Unix, so backup/restore and process cleanup are the most likely places to reveal actual application portability defects after the harness is fixed.

## Remote Commander prerequisite

A Windows implementation host also needs an approved Remote Commander target that can:

- execute PowerShell/processes;
- access the repository/worktree;
- run Git;
- run Python and Just;
- push branches and perform the repository's GitHub lifecycle.

The current device name `u24-gpt` cannot simply be reinterpreted as Windows. The protocol/manifest should carry the approved target explicitly.

## Recommended host-neutral protocol model

Do **not** create a separate Windows fork of v4/v5.

Introduce the next protocol revision with:

```text
execution_host:
  connector: Remote Commander
  device: <manifest supplied>
  os: linux | windows
```

Rules common to both:

- exact seeded branch/history invariants;
- same focused/canonical verification;
- same PR/CI/merge lifecycle;
- same stop conditions.

Host-specific behavior should be limited to:
- command-shell syntax;
- interpreter executable/location;
- temporary directory;
- process management.

Repository verification commands themselves should become platform-neutral Python/Just entry points.

## Estimated scope

A reasonable portability stage is small:

1. platform-neutral migration-check/retrieval temporary handling;
2. platform-neutral wheel/install smoke test;
3. native Windows full-suite corrections, especially SQLite locking;
4. host-neutral v4/v5 successor protocol;
5. one Windows implementation-agent pilot assignment through PR/CI/merge.

After that pilot succeeds, Windows can be treated as a first-class implementation host.

## Current answer

- **Can the application run/develop on Windows 11?** Very likely yes; Windows data paths are already explicitly designed and tested.
- **Can the current v4/v5 implementation agent legally and reliably run there now?** No.
- **Is making it possible expensive?** No. The blockers are concentrated in the verification harness and hard-coded execution-host policy, not the product architecture.
