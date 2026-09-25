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
| Environment and secrets | `/home/rdu01/.local/state/ah-there-it-is/runtime.env` | directory `0700`, file `0600`; outside Git |
| Service definitions | user `systemd`, linked from `deploy/systemd/` | `systemctl --user` |
| Logs | user journal (`journalctl --user -u ...`) | host journal policy |

The parent `/home/rdu01/.config` is root-owned on this host, but its existing
`systemd/user` subdirectory is writable by `rdu01`. The state directory is
therefore the usable secrets location. Keep the Telegram lock file across
deployments; never remove or replace it while any poller can run.

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
ln -s /home/rdu01/projects/0091-deployment-readiness \
  /home/rdu01/apps/ah-there-it-is/current
```

Create `runtime.env` outside Git with mode `0600` and these non-secret lines:

```text
AH_THERE_IT_IS_ENV=production
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db
```

Install `AH_THERE_IT_IS_TELEGRAM_BOT_TOKEN` and
`AH_THERE_IT_IS_TELEGRAM_ALLOWED_USER_ID` there only when ready to activate the
real bot. Add the selected provider/model settings there if the heuristic
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
  .venv/bin/python -m ah_there_it_is.storage_cli migration-check
chmod 600 /home/rdu01/.local/share/ah-there-it-is/inventory.db
systemctl --user link "$PWD/deploy/systemd/ah-there-it-is-web.service" \
  "$PWD/deploy/systemd/ah-there-it-is-telegram.service"
systemctl --user daemon-reload
systemctl --user enable --now ah-there-it-is-web.service
curl --fail http://127.0.0.1:8000/health
```

Expected: `migration_check: ok`, web `active`, health `status: ok`. Runtime
startup does not migrate or repair; a mismatched/missing schema makes the unit
fail. `systemctl --user link` may report an existing link on repeat installs.

## Normal stop, restart, and upgrade

```bash
systemctl --user stop ah-there-it-is-telegram.service ah-there-it-is-web.service
systemctl --user show ah-there-it-is-telegram.service -p MainPID -p ActiveState
systemctl --user show ah-there-it-is-web.service -p MainPID -p ActiveState
# Both MainPID values must be 0 before changing code or schema.
```

For an update, take a validated backup (below), prepare the new checkout and
venv, then atomically repoint `current` while both units are stopped:

```bash
ln -s /absolute/path/to/new-checkout /home/rdu01/apps/ah-there-it-is/current.next
mv -Tf /home/rdu01/apps/ah-there-it-is/current.next \
  /home/rdu01/apps/ah-there-it-is/current
```

Run the new
checkout's explicit `storage_cli upgrade` and `migration-check`, then start
web and, only with valid real Telegram settings, the bot. `systemctl --user
restart ah-there-it-is-telegram.service` stops the old unit before starting
the new one. The database-derived kernel lock also rejects a concurrent manual
poller before its first Telegram call. It is released after process exit or
crash. The lock is host-local: do not run another host against this same bot.

```bash
systemctl --user start ah-there-it-is-web.service
systemctl --user enable --now ah-there-it-is-telegram.service
systemctl --user show ah-there-it-is-telegram.service -p MainPID -p ActiveState
journalctl --user -u ah-there-it-is-telegram.service -n 30 --no-pager
```

On a failed upgrade, stop both units. A code rollback is safe only if the old
package accepts the current schema; confirm `migration-check` with that package
before restarting it. Otherwise restore a validated pre-upgrade backup by the
documented storage CLI procedure during downtime. Never overwrite the active
database merely to rehearse rollback.

## Backup and recovery rehearsal

Use a unique name and `umask 077`. These commands use the explicit active DB
setting shown above (or a trusted private shell environment):

```bash
umask 077
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db \
  .venv/bin/python -m ah_there_it_is.storage_cli backup \
  /home/rdu01/.local/share/ah-there-it-is/backups/pre-upgrade.db
.venv/bin/python -m ah_there_it_is.storage_cli validate \
  /home/rdu01/.local/share/ah-there-it-is/backups/pre-upgrade.db
AH_THERE_IT_IS_DATABASE_URL=sqlite:////home/rdu01/.local/share/ah-there-it-is/inventory.db \
  .venv/bin/python -m ah_there_it_is.storage_cli restore-rehearsal \
  /home/rdu01/.local/share/ah-there-it-is/backups/pre-upgrade.db
```

Expected: integrity `ok`, no foreign-key violations, and rehearsal `ok: true`.
The rehearsal creates a scratch active database; it does not replace the
authoritative DB. Keep an off-machine backup copy through external operations.

## Telegram no-message acceptance

On this host, a controlled probe used `deploy/probes/fake_telegram_api.py`, an
empty `getUpdates` response, and a non-production token. It sent no messages.
With the fake API on `127.0.0.1:18791`, temporary probe-only Telegram settings
in the private `runtime.env` let the real `systemd` Telegram unit hold the
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

## Host observations at 2026-09-25 issuance checkout

Verified: Python 3.12 venv installation succeeded; user `systemd` is running
with `Linger=yes`; web unit is enabled and active on loopback; migration head is
`2b8d5f1a4c20`; the new active DB is empty; web stop/start/restart and the
schema/data signature check succeeded; backup, validation, and scratch restore
rehearsal succeeded; the Telegram singleton and restart/upgrade probes
succeeded without external calls; a SIGKILL of the web main process caused
`systemd` to restart it with a new PID and restored health. The private runtime
file contains only the environment and DB URL above. The Telegram unit is
linked but disabled and stopped because no production token or allowed user ID
was supplied.

Remaining host inputs: install the actual Telegram token/allowed user ID in the
private file and select/provision the intended live LLM provider. Then run the
real bot activation and a non-mutating connectivity check under operator
control. Backup retention and off-machine copies remain external policy.
