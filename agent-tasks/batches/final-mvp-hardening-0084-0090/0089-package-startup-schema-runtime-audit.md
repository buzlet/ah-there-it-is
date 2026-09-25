# 0089 — Package, startup, schema and runtime semantics audit

## Objective

Check code-level runtime readiness without pretending the sandbox is the deployment server.

## Required work

Verify:

- installed wheel contains migrations/templates/required package data;
- Web and Telegram runtime entrypoints use read-only schema compatibility gates;
- startup never auto-migrates or silently repairs;
- doctor remains read-only except explicit FTS repair;
- missing/invalid runtime configuration fails safely without secret leakage;
- runtime CLI commands import and construct services without unintended startup side effects;
- migration head/fresh DB/upgrade DB checks remain valid;
- sandbox bootstrap/offline wheel-build path remains coherent.

You may use temporary paths inside the sandbox for package/runtime tests.

## Explicit boundary

Do **not** configure or design:

- systemd/service units;
- production env/secrets files;
- target filesystem/data/log paths;
- actual deployment checkout/install location;
- server user/group/permissions;
- production restart policy;
- real backup schedule/off-machine copy;
- host firewall/network configuration.

Any issue whose correct validation requires the real target server must be recorded as:

`DIRECT FOLLOW-UP: <exact requirement/reproduction/check>`

for the later Direct 0091+ batch.

## Focused verification

    .venv/bin/python -m pytest -q       tests/test_wheel_migrations.py       tests/test_migrations.py       tests/test_runtime_cli.py       tests/test_database_doctor.py       tests/test_storage.py       tests/test_trace_config_privacy.py       tests/test_app.py       tests/test_telegram_runtime.py
    make migration-check
    make compile
    git diff --check
