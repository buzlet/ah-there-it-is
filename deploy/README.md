# U24 single-user deployment

Run these commands as `rdu01`, without `sudo`. The web UI has no authentication;
the unit binds only `127.0.0.1:8000`. The Telegram unit must stay disabled until
the real token and allowed user ID are installed out of band.

## Durable layout

| Purpose | Path | Access |
| --- | --- | --- |
| Current code + repository-local venv | `/home/rdu01/apps/ah-there-it-is/current` (symlink to one checkout) | `rdu01` |
| Active SQLite + WAL + Telegram lock | `/home/rdu01/.local/share/ah-there-it-is/` | directory `0700`, DB/lock `0600` |
| Backups | `/home/rdu01/.local/share/ah-there-it-is/backups/` | directory `0700`, files `0600` |
| Common environment | `/home/rdu01/.local/state/ah-there-it-is/runtime.env` | directory `0700`, file `0600`; outside Git |
| Telegram secrets | `/home/rdu01/.local/state/ah-there-it-is/telegram.env` | directory `0700`, file `0600`; outside Git; Telegram unit only |
| Service definitions | `/home/rdu01/.config/systemd/user/ah-there-it-is-*.service` | regular copied files, independent of old checkouts |
| Logs | user journal (`journalctl --user -u ...`) | host journal policy |

The parent `/home/rdu01/.config` is root-owned on this host, but its existing
`systemd/user` subdirectory is writable by `rdu01`. The state directory is
therefore the usable secrets location. A private `locks/` child holds a
SHA-256-derived bot identity lock; the raw token is never a path component.
The DB also has its own lock beside `inventory.db`. Keep both lock files across
deployments; never remove or replace them while any poller can run.

## First install and explicit schema setup

The checkout and its `.venv` must be at the target of `current`. From the
checkout, run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
install -d -m 700 /home/rdu01/apps/ah-there-it-is \
  /home/rdu01/.local/share/ah-there-it-is \
  /home/rdu01/.local/share/ah-there-it-is/backups \
  /home/rdu01/.local/state/ah-there-it-is
```

Create `runtime.env` outside Git with mode `0600` and these common lines:

```text
AH_THERE_IT_IS_ENV=production
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db
```

Create a separate `telegram.env` outside Git with mode `0600` (empty until bot
activation). Install `AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN` and
`AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID` only in `telegram.env` when ready to
activate the real bot. The web unit explicitly unsets those variables even if
they enter its manager environment. Add selected provider/model settings to
`runtime.env` if the heuristic
provider is not the intended production choice. Do not put secret values in
shell commands, Git, screenshots, or issue/PR text. Production mode requires an
explicit absolute SQLite URL; the bot also requires both Telegram settings.

Explicitly create/upgrade the schema before starting either unit. These
commands use only the non-secret DB setting. Do not source an untrusted
environment file as shell code:

```bash
umask 077
AH_THERE_IT_IS_ENV=production \
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db \
  .venv/bin/python -m ah_there_it_is.storage_cli upgrade
AH_THERE_IT_IS_ENV=production \
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db \
  .venv/bin/ah-there-it-is schema-check --require-production
chmod 600 /home/rdu01/.local/share/ah-there-it-is/inventory.db
if [ ! -e /home/rdu01/.local/state/ah-there-it-is/telegram.env ]; then
  install -m 600 /dev/null /home/rdu01/.local/state/ah-there-it-is/telegram.env
fi
.venv/bin/python deploy/install_user_units.py --switch-release "$PWD"
systemctl --user enable --now ah-there-it-is-web.service
curl --fail http://127.0.0.1:8000/health
```

Expected: matching `database_heads` and `packaged_heads`, web `active`, health
`status: ok`. Runtime
startup does not migrate or repair; a mismatched/missing schema makes the unit
fail. The read-only preflight examines a private temporary copy because SQLite
can alter the source `-shm` even with a read-only connection. The installer
copies unit definitions into the stable user unit directory, runs
`daemon-reload`, and verifies `FragmentPath`, effective preflight and start
commands, and environment boundaries. Both units call
`schema-check --require-production` before `ExecStart`; missing or development
mode in `runtime.env` stops startup while ordinary local CLI commands retain
their development default.

## Normal stop, restart, and upgrade

```bash
systemctl --user stop ah-there-it-is-telegram.service ah-there-it-is-web.service
systemctl --user show ah-there-it-is-telegram.service -p MainPID -p ActiveState
systemctl --user show ah-there-it-is-web.service -p MainPID -p ActiveState
# Both MainPID values must be 0 before changing code or schema.
```

For an update, take a validated backup (below), prepare the new checkout and
venv, then use that checkout's installer while both units are stopped:

```bash
cd /absolute/path/to/new-checkout
.venv/bin/python deploy/install_user_units.py --switch-release "$PWD"
systemctl --user show ah-there-it-is-web.service -p FragmentPath -p NeedDaemonReload -p ExecStartPre
systemctl --user show ah-there-it-is-telegram.service -p FragmentPath -p NeedDaemonReload -p EnvironmentFiles
```

The installer refuses to switch while either unit has a live PID. It replaces
the `current` symlink atomically, reloads systemd and checks effective unit
settings. The installed definitions remain usable after deleting the old
checkout. Run the new checkout's explicit `storage_cli upgrade` and read-only
`schema-check --require-production`, then start web and, only with valid real
Telegram settings, the bot. `systemctl --user restart ah-there-it-is-telegram.service` stops the old
unit before starting
the new one. Kernel locks on both bot identity and database reject a concurrent
manual poller before its first Telegram call, including when the same bot uses
a different DB path. They are released after process exit or crash. These
locks are host-local: do not run another host against this same bot.

```bash
systemctl --user start ah-there-it-is-web.service
systemctl --user enable --now ah-there-it-is-telegram.service
systemctl --user show ah-there-it-is-telegram.service -p MainPID -p ActiveState
journalctl --user -u ah-there-it-is-telegram.service -n 30 --no-pager
```

The Telegram unit uses `Type=notify`. It remains `activating` until its first
successful `getUpdates`; a live PID alone is not readiness. HTTP/API 401 fails
immediately with process status `2`. A 409 conflict fails after three
consecutive attempts with status `2`. Systemd does not restart those permanent
failures (`RestartPreventExitStatus=2`). 429, 5xx and transport failures retry;
they do not report ready until polling succeeds. Use
`.venv/bin/python deploy/probes/telegram_systemd_status.py` for the reproducible
scratch/fake-API host probe; it never contacts Telegram or sends messages.

For the release lifecycle probe, run
`.venv/bin/python deploy/probes/release_lifecycle.py` from the active checkout.
It prepares two disposable installed release copies, stops and starts only the
web unit, switches `current` to each, deletes the old copy, verifies web health
and effective stable unit paths, then restores the original release. It requires
the Telegram unit to be stopped.

To repeat the production-mode gate safely, run
`.venv/bin/python deploy/probes/production_mode_preflight.py`. It uses the
shipped `ExecStartPre` command in transient user-systemd units with scratch
configuration and a harmless `ExecStart` marker, then verifies unset,
development, malformed, missing-DB, relative-DB and valid-production cases.

On a failed upgrade, stop both units. A code-only rollback is safe only if the
old package accepts the upgraded schema; check it with that package before
restarting. The ordinary `storage_cli restore` and `restore-rehearsal` require
the installed package's current revision and cannot restore a pre-upgrade
backup across schema revisions. For a schema rollback use the separate
procedure below. Never overwrite the active database merely to rehearse it.

## Backup and recovery rehearsal

Use `backup-auto` before each deployment. It adds a UTC timestamp and random
suffix and still uses the backup CLI's no-overwrite publication. These commands
use the explicit active DB setting shown above (or a trusted private shell
environment):

```bash
umask 077
backup_report=$(AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db \
  .venv/bin/python -m ah_there_it_is.storage_cli backup-auto \
  /home/rdu01/.local/share/ah-there-it-is/backups)
backup=$(printf '%s' "$backup_report" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["path"])')
.venv/bin/python -m ah_there_it_is.storage_cli validate "$backup"
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db \
  .venv/bin/python -m ah_there_it_is.storage_cli restore-rehearsal \
  "$backup"
```

Expected: integrity `ok`, no foreign-key violations, and rehearsal `ok: true`.
The rehearsal creates a scratch active database; it does not replace the
authoritative DB. Keep an off-machine backup copy through external operations.

### Roll back across schema revisions

Retain the old checkout, its installed venv, and the validated pre-upgrade
backup path (`$backup` above) until the new release is accepted. If the upgrade
changed schema and the old package rejects the upgraded DB, stop both services
and run the new release's separate rollback tool. Supply the old package's
Python interpreter and its exact Alembic revision. Example for the tested
`1a7c4e9d2b10` to `2b8d5f1a4c20` transition:

```bash
systemctl --user stop ah-there-it-is-telegram.service ah-there-it-is-web.service
systemctl --user show ah-there-it-is-web.service ah-there-it-is-telegram.service -p MainPID
new_release=/absolute/path/to/new-checkout
old_release=/absolute/path/to/old-checkout
"$new_release/.venv/bin/python" "$new_release/deploy/cross_schema_rollback.py" \
  /home/rdu01/.local/share/ah-there-it-is/inventory.db \
  "$backup" "$old_release/.venv/bin/python" \
  --old-revision 1a7c4e9d2b10
cd "$old_release"
.venv/bin/python deploy/install_user_units.py --switch-release "$PWD"
systemctl --user start ah-there-it-is-web.service
```

The rollback tool requires both service PIDs to be zero. It validates the old
backup with the old installed package, checkpoints the upgraded DB's WAL,
creates and validates a uniquely named upgraded safety backup, stages and
validates the old DB, moves the upgraded DB and sidecars into a private
quarantine directory, and publishes the old DB with a no-overwrite hard link.
It syncs files and directories before reporting success, validates the restored
DB with the old package, and removes empty WAL/SHM left by validation. The
output names both the upgraded safety backup and quarantine; keep them until
recovery is confirmed. If a competing process recreates the active path, the
tool refuses to overwrite it and retains the upgraded copy in quarantine.
Resolve such an interruption under downtime using those preserved files; do
not start either unit on an uncertain DB. Switch to the old release only after
the tool succeeds and verify its effective units and web health before enabling
Telegram. This is a maintenance operation with exclusive database ownership.

The Direct rehearsal is `.venv/bin/python deploy/probes/cross_schema_rollback.py`.
It creates a scratch DB with a historical old package, validates its backup,
upgrades the scratch DB, leaves committed upgraded WAL after process death,
executes the rollback command under stopped units, verifies the old package and
old web server, then restores the production web unit. It never replaces the
production DB.

## Telegram no-message acceptance

On this host, a controlled probe used `deploy/probes/fake_telegram_api.py`, an
empty `getUpdates` response, and a non-production token. It sent no messages.
With the fake API on `127.0.0.1:18791`, temporary probe-only Telegram settings
in the private `telegram.env` let the real `systemd` Telegram unit hold the
production DB lock. A second `ah-there-it-is telegram-bot` using the same DB
exited `2` with `Telegram poller already owns database lock`; the first PID
remained active. Unit restart replaced the PID and the old PID was gone. The
same rejection held after stop/install/explicit upgrade/start. Remove the
probe settings, disable/stop the unit, and stop the fake API afterwards.

The focused test `tests/test_telegram_deployment.py` independently starts two
processes against one lock file and reopens a file-backed migrated DB across
both crash windows. A committed mutation is replayed once. A reply sent before
checkpoint can be sent again; Telegram's API supplies no atomic send/checkpoint
transaction. This is the remaining external-reply duplication risk.

### Interrupted Telegram request recovery

If a poller dies after reserving `telegram:<update_id>`, the durable request
can remain `processing`; an application failure can leave it `failed`. The bot
exits with status `2` at that update and `RestartPreventExitStatus=2` keeps the
service stopped. It does not silently retry an uncertain mutation or skip the
queue. The original request and each recovery attempt remain in the DB audit.

Stop the Telegram unit and confirm `MainPID=0` before operator recovery. Use a
private `systemd-run` invocation to load the secret environment file without
putting the token in argv. Replace `101` with the blocked update ID:

```bash
systemctl --user stop ah-there-it-is-telegram.service
systemctl --user show ah-there-it-is-telegram.service -p MainPID -p ActiveState
systemd-run --user --wait --pipe --collect -P \
  -p EnvironmentFile=/home/rdu01/.local/state/ah-there-it-is/runtime.env \
  -p EnvironmentFile=/home/rdu01/.local/state/ah-there-it-is/telegram.env \
  /home/rdu01/apps/ah-there-it-is/current/.venv/bin/ah-there-it-is \
  telegram-recovery-status 101
```

Confirm the source is `processing` or `failed`, has no committed run, and the
prior process is gone. Inventory mutations and final request completion share
one SQLite transaction, so an unfinished request has no committed inventory
effect. After that operator decision, execute one new durable attempt; the
flag is deliberately required:

```bash
systemd-run --user --wait --pipe --collect -P \
  -p EnvironmentFile=/home/rdu01/.local/state/ah-there-it-is/runtime.env \
  -p EnvironmentFile=/home/rdu01/.local/state/ah-there-it-is/telegram.env \
  /home/rdu01/apps/ah-there-it-is/current/.venv/bin/ah-there-it-is \
  telegram-recover 101 --attempt 1 --confirm-atomic-rollback
systemctl --user start ah-there-it-is-telegram.service
```

On redelivery the bot sends the committed recovery result, checkpoints update
101, then processes later updates. If an attempt fails or dies, inspect status
again and use the next unused attempt number. Never reuse the original key or
repeat a completed recovery. A reply may still duplicate if a send succeeded
but its checkpoint did not commit.

## Host observations

Verified: Python 3.12 venv installation succeeded; user `systemd` is running
with `Linger=yes`; web unit is enabled and active on loopback; migration head is
`2b8d5f1a4c20`; the new active DB is empty; web stop/start/restart and the
schema/data signature check succeeded; backup, validation, and scratch restore
rehearsal succeeded; the Telegram singleton and restart/upgrade probes
succeeded without external calls; a SIGKILL of the web main process caused
`systemd` to restart it with a new PID and restored health. The private runtime
file contains only the environment and DB URL above. The Telegram unit is
installed as a stable unit but disabled and stopped because no production token
or allowed user ID was supplied. On 2026-09-26 the Direct release probe switched
between two isolated installed copies, deleted the old copy, verified the new
web process and health, and restored the checkout. `FragmentPath` and effective
unit settings remained stable after `daemon-reload`. With a temporary synthetic
Telegram credential in the common file, the web process environment did not
contain the credential; the original common file was restored afterwards.

Remaining host inputs: install the actual Telegram token/allowed user ID in
`telegram.env` and select/provision the intended live LLM provider. Then run the
real bot activation and a non-mutating connectivity check under operator
control. Backup retention and off-machine copies remain external policy.
