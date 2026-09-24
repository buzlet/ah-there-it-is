# Assignment 0022: explicit non-loopback serve guard

Protocol: `agent-tasks/common/v5-batch.md` wrapping the v4 per-assignment lifecycle.

Branch: `feat/hardening-nonlocal-serve-guard`

## Objective

Prevent accidental exposure of the unauthenticated local web application on non-loopback interfaces while preserving explicit operator-controlled remote binding.

## Required behavior

- Installed `ah-there-it-is serve` keeps the default host `127.0.0.1`.
- Add explicit CLI flag:

  `--allow-nonlocal`

- Without that flag, reject non-loopback hosts before starting Uvicorn.
- Treat these as loopback-safe without the flag:
  - IPv4 addresses in `127.0.0.0/8`;
  - IPv6 `::1`;
  - hostname `localhost` case-insensitively.
- Treat wildcard addresses (`0.0.0.0`, `::`) and all other hostnames/IPs as non-loopback.
- When `--allow-nonlocal` is supplied for a non-loopback host:
  - allow startup;
  - print a concise warning to stderr that the application has no authentication and is being exposed beyond loopback.
- Supplying `--allow-nonlocal` with a loopback host is harmless.
- Keep `just serve` local-only; do not add the override there.
- No environment-variable bypass. The explicit CLI flag is intentionally required on every nonlocal installed-server start.
- The guard must not change schema gating or create/migrate data.

## Coverage

- 127.0.0.1, another 127/8 address, ::1, localhost;
- 0.0.0.0, ::, LAN IPv4, public IPv4/IPv6, arbitrary hostname;
- nonlocal rejection occurs before `uvicorn.run`;
- explicit opt-in invokes Uvicorn with the requested host and emits warning;
- installed-wheel CLI behavior.

## Constraints

This is an accidental-exposure guard, **not authentication**. Do not add users/passwords/tokens/TLS/reverse-proxy configuration, service-manager integration, dependencies, schema changes, provider changes or workflow changes.

## Focused verification

Run focused runtime CLI/installed-wheel tests, then the canonical v4 verification set.
