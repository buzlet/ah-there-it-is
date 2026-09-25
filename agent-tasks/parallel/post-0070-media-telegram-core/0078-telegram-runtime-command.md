# 0078 — Telegram runtime command and operational loop

Status: draft task spec; reconcile after 0061-0070 merge.

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
