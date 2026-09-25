# 0078 — Telegram runtime command and operational loop

Status: issued implementation spec for batch 0071–0080.

## Objective

Provide an explicit long-running Telegram bot process integrated with the existing package/runtime configuration.

## CLI

Add an explicit command, conceptually:

    ah-there-it-is telegram-bot

Do not start Telegram polling as a side effect of FastAPI startup.

## Runtime loop

- construct DB/session/LLM/application chat service using existing Settings/factories;
- construct Telegram client/adapter;
- perform long polling with bounded retry/backoff;
- clean shutdown on normal termination;
- no daemonization/systemd/scheduler logic inside the application.

## Adapter-only commands

/start and /help may be handled without AgentRunner.

A minimal diagnostic/status command is optional if it does not expose secrets or inventory data unnecessarily.

All inventory actions remain ordinary Russian natural-language messages.

## Secrets

Startup validation may report that required Telegram settings are missing, but must never print the token.


## Issued runtime constraints

- Extend the existing installed `ah-there-it-is` CLI with an explicit `telegram-bot` subcommand.
- The bot command must pass the same read-only runtime schema gate before service startup.
- Missing Telegram settings fail only the Telegram command; they must not make ordinary Web/runtime imports fail.
- No daemonization, systemd installation, background thread at FastAPI startup or webhook mode.
- Graceful KeyboardInterrupt/termination behavior is sufficient for core MVP.
- `/start` and `/help` may be adapter-only and must not invoke inventory mutations.

## Focused verification

Create `tests/test_telegram_runtime.py`.

Run exactly:

    .venv/bin/python -m pytest -q tests/test_telegram_runtime.py tests/test_runtime_cli.py tests/test_trace_config_privacy.py -k "telegram or runtime or cli or token or schema"
    make compile
    git diff --check
