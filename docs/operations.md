# Operations runbook

Day-2 procedures for running `am4bot` in production. The
[README](../README.md) has the quick-reference commands; this file has
the longer-form drills (backup/restore, upgrades, recovery).

> All commands assume you're working from the repo root unless
> noted. Replace `deploy/docker-compose.yml` with `-f deploy/docker-compose.yml`
> in your shell history if you `cd deploy/` first.

## Table of contents

- [Health check](#health-check)
- [Logs](#logs)
- [Backup and restore](#backup-and-restore)
- [Upgrading the bot](#upgrading-the-bot)
- [Recovering a corrupt SQLite DB](#recovering-a-corrupt-sqlite-db)
- [Resetting price history](#resetting-price-history)
- [Rotating the Discord token](#rotating-the-discord-token)
- [Rotating the AM4Help token](#rotating-the-am4help-token)
- [Tuning the log driver](#tuning-the-log-driver)
- [Tuning the poll interval](#tuning-the-poll-interval)

## Health check

Quick "is the bot alive and processing prices?" check:

```bash
# 1. Container running and healthy?
docker compose -f deploy/docker-compose.yml ps

# 2. Discord gateway connected? (look for "logged in as ..." line)
docker compose -f deploy/docker-compose.yml logs --tail=200 am4bot | grep "logged in as"

# 3. /status command in Discord shows recent timestamps?
#    (or query the DB directly:)
docker compose -f deploy/docker-compose.yml exec am4bot \
    python -c "import sqlite3,os; \
        c=sqlite3.connect(os.environ['DB_PATH']); \
        [print(r) for r in c.execute('SELECT commodity, price, ts, source FROM prices ORDER BY ts DESC LIMIT 10')]"
```

Healthy looks like: container `Up`, a recent "logged in as" line, and
fresh `ts` values (within the last `POLL_INTERVAL` if `PRICE_SOURCE=am4help`).

## Logs

```bash
# Follow live
docker compose -f deploy/docker-compose.yml logs -f am4bot

# Last 200 lines
docker compose -f deploy/docker-compose.yml logs --tail=200 am4bot

# Since a specific time (relative or ISO 8601)
docker compose -f deploy/docker-compose.yml logs --since=1h am4bot
docker compose -f deploy/docker-compose.yml logs --since=2026-01-15T00:00 am4bot
```

Logs are written by the `json-file` driver, capped at 3 × 10 MB by
`docker-compose.yml`. Older entries roll off automatically.

To bump verbosity temporarily, set `LOG_LEVEL=DEBUG` in
`deploy/.env` and `docker compose up -d` (no rebuild needed). Revert
to `INFO` when done — `DEBUG` is noisy.

## Backup and restore

The DB is the only stateful piece. Code and config can be reproduced
from git + `.env`.

### Backup the volume

```bash
mkdir -p backups
docker run --rm \
    -v am4bot-data:/data \
    -v "$PWD/backups:/backup" \
    alpine \
    tar czf /backup/am4bot-data-$(date +%F-%H%M).tar.gz -C /data .
```

This produces `backups/am4bot-data-<date>.tar.gz`. Schedule via cron
on the host:

```cron
# /etc/cron.daily/am4bot-backup
30 4 * * *  cd /opt/AM4-Fuel-CO2-Prices && \
            docker run --rm -v am4bot-data:/data -v /opt/am4bot-backups:/backup alpine \
              tar czf /backup/am4bot-data-$(date +\%F).tar.gz -C /data . && \
            find /opt/am4bot-backups -name 'am4bot-data-*.tar.gz' -mtime +30 -delete
```

(Adjust paths to your install. The `find` line keeps 30 days of
backups.)

### Hot backup (consistent snapshot of the live DB)

The `tar` approach above copies the DB file while the bot may be
writing to it. SQLite's WAL mode plus `aiosqlite` makes torn-write
corruption very unlikely, but if you want a *guaranteed* consistent
snapshot:

```bash
docker compose -f deploy/docker-compose.yml exec am4bot \
    python -c "import sqlite3,os; \
        src = sqlite3.connect(os.environ['DB_PATH']); \
        dst = sqlite3.connect('/data/prices-snapshot.db'); \
        src.backup(dst); dst.close(); src.close(); \
        print('snapshot written to /data/prices-snapshot.db')"

# then tar /data/prices-snapshot.db as above, and remove the snapshot
docker compose -f deploy/docker-compose.yml exec am4bot \
    rm /data/prices-snapshot.db
```

`sqlite3.Connection.backup()` is the official online-backup API and
holds a read lock long enough to copy pages atomically.

### Restore from backup

```bash
# 1. Stop the bot
docker compose -f deploy/docker-compose.yml down

# 2. Wipe the volume
docker volume rm deploy_am4bot-data

# 3. Recreate the volume and untar the backup into it
docker volume create deploy_am4bot-data
docker run --rm \
    -v deploy_am4bot-data:/data \
    -v "$PWD/backups:/backup:ro" \
    alpine \
    tar xzf /backup/am4bot-data-2026-01-15.tar.gz -C /data

# 4. Start the bot
docker compose -f deploy/docker-compose.yml up -d
```

> The volume name has a `deploy_` prefix because that's the docker
> compose project name (the directory containing `docker-compose.yml`).
> Run `docker volume ls` to confirm the actual name.

## Upgrading the bot

```bash
cd /path/to/AM4-Fuel-CO2-Prices
git fetch origin
git pull origin main                       # or your deployed branch
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f am4bot
```

The `--build` flag rebuilds the image from the new source. The DB
volume is untouched, so price history persists.

If a future release introduces a schema change, the upgrade notes for
that release will document the migration. Always backup before
upgrading across a major version bump.

## Recovering a corrupt SQLite DB

Symptoms: bot logs `sqlite3.DatabaseError: database disk image is
malformed` or `database is locked` that won't clear.

**Step 1 — confirm corruption.**

```bash
docker compose -f deploy/docker-compose.yml down
docker run --rm -v am4bot-data:/data alpine \
    sh -c 'apk add -q sqlite && sqlite3 /data/prices.db "PRAGMA integrity_check;"'
```

If the output is `ok`, it's not corruption — investigate the
underlying error instead.

**Step 2 — try the SQLite recovery tool.**

```bash
docker run --rm -v am4bot-data:/data alpine \
    sh -c 'apk add -q sqlite && \
           sqlite3 /data/prices.db ".recover" | sqlite3 /data/prices-recovered.db && \
           mv /data/prices.db /data/prices-corrupt-$(date +%s).db && \
           mv /data/prices-recovered.db /data/prices.db'

docker compose -f deploy/docker-compose.yml up -d
```

`.recover` reads as much salvageable data as possible into a fresh
file. The original corrupt file is renamed (not deleted) so you can
forensics it later.

**Step 3 — if `.recover` fails, restore from the most recent backup**
(see [Restore from backup](#restore-from-backup) above).

## Resetting price history

If you want a clean slate (e.g. moved to a new account, want to
discard test data) without losing the volume entirely:

```bash
# Drop just the rows
docker compose -f deploy/docker-compose.yml exec am4bot \
    python -c "import sqlite3,os; \
        c=sqlite3.connect(os.environ['DB_PATH']); \
        c.execute('DELETE FROM prices'); c.commit(); \
        print('cleared'); c.close()"

# Or drop the entire volume (destructive, requires recreate)
docker compose -f deploy/docker-compose.yml down
docker volume rm deploy_am4bot-data
docker compose -f deploy/docker-compose.yml up -d   # new empty volume
```

The schema is recreated by `Store.init()` on the next start, so
recreating the volume is safe.

## Rotating the Discord token

You'll need to do this if the token leaks (e.g. accidentally pushed to
a public repo).

1. Open <https://discord.com/developers/applications>, pick your app,
   open the **Bot** tab, click **Reset Token**, copy the new value.
2. Edit `deploy/.env`, replace `DISCORD_TOKEN=<old>` with the new value.
3. `docker compose -f deploy/docker-compose.yml up -d` (no rebuild
   required — env is loaded at start).
4. Verify in logs: `logged in as <bot-name>`. The old token is now
   revoked and the bot reconnects with the new one.

## Rotating the AM4Help token

1. Get a new token from the AM4Help API owner.
2. Edit `deploy/.env`: `AM4HELP_TOKEN=<new>`.
3. `docker compose -f deploy/docker-compose.yml up -d`.
4. Watch logs for `am4help fetch failed` errors after the next tick.
   None means rotation succeeded.

## Tuning the log driver

The default in `docker-compose.yml`:

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "3"
```

That's 30 MB ceiling per container. Bump or shrink in
`deploy/docker-compose.yml`, then `docker compose up -d` (no rebuild).
Switching drivers entirely (e.g. to `journald` so logs go into the
host's journal) is also a one-line change:

```yaml
logging:
  driver: journald
  options:
    tag: "am4bot"
```

After which `journalctl CONTAINER_TAG=am4bot -f` follows the logs
alongside the rest of the host.

## Tuning the poll interval

`POLL_INTERVAL` (seconds) controls the `tasks.loop` cadence. Defaults
to 300 (5 min). Considerations:

- **Lower** (e.g. 60s): faster detection of price drops, but more
  upstream API load and more rows when prices oscillate. If the
  upstream rate-limits, the adapter logs `am4help fetch failed: ...
  429` and skips the tick.
- **Higher** (e.g. 1800s = 30 min): minimal upstream load, but you
  may miss short-lived dips. `/fuel best` is only as good as the
  samples in the DB.

Edit `deploy/.env` and `docker compose up -d`. No rebuild needed.
