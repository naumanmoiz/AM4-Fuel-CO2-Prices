# AM4-Fuel-CO2-Prices

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![discord.py 2.4+](https://img.shields.io/badge/discord.py-2.4%2B-7289da.svg)](https://discordpy.readthedocs.io/)
[![Docker](https://img.shields.io/badge/docker-compose-2496ED.svg)](https://docs.docker.com/compose/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Private Discord bot that tracks Airline Manager 4 fuel and CO₂ quota prices
and exposes them via slash commands. Designed to run as a Docker container
on a Linux VM (home lab / Proxmox).

## Table of contents

- [Slash commands](#slash-commands)
- [Architecture](#architecture)
- [Quick start (Docker Compose)](#quick-start-docker-compose)
- [Discord developer-portal setup](#discord-developer-portal-setup)
- [Environment reference](#environment-reference)
- [Configuring the AM4Help adapter](#configuring-the-am4help-adapter)
- [Day-2 ops](#day-2-ops)
- [Troubleshooting](#troubleshooting)
- [Development without Docker](#development-without-docker)
- [Further reading](#further-reading)

## Slash commands

| Command | Description |
| --- | --- |
| `/fuel current` | Latest known fuel price |
| `/fuel best` | Lowest fuel price seen in the last 24h |
| `/fuel interval interval:<1h\|4h\|12h\|24h\|7d>` | Min / avg / max over the chosen window |
| `/co2 current \| best \| interval` | Same shape as `/fuel`, for CO₂ quota |
| `/submit commodity:<fuel\|co2> price:<n>` | Manual price entry (allowlist enforced) |
| `/status` | Last seen prices for both commodities |

Timestamps in embeds use Discord's `<t:UNIX:R>` syntax, so each user sees
relative times in their own timezone (e.g. "5 minutes ago").

### Example response shapes

`/fuel current` →

```
Fuel — current
Price       Updated
480.00      5 minutes ago
source: am4help
```

`/fuel interval interval:24h` →

```
Fuel — last 24h
Min       Avg       Max       Samples   From
460.00    472.50    492.00    18        24 hours ago
```

`/status` →

```
AM4 prices — status
Fuel:  480.00  ·  5 minutes ago  ·  `am4help`
CO₂:   no data
am4bot v0.1.0
```

## Architecture

- Python 3.11+, `discord.py` 2.4+ slash commands via `app_commands`
- `aiosqlite` price store, single `prices` table, one row per **price change**
  (deduplicated via `insert_if_changed`)
- Pluggable price source via the `PriceAdapter` Protocol. Two adapters
  ship today:
  - `am4help` — pulls from `api.am4help.com` with an `x-access-token`
    header. Endpoint path and JSON field paths are configurable via env,
    so you can re-point the adapter once you confirm the real prices
    endpoint with the API owner without code changes.
  - `null` — no polling; data only enters via `/submit`. Useful for
    bootstrapping before the upstream API is wired up.
- Background poller is a `discord.ext.tasks.loop` (default 5 min).

For a deeper walkthrough of the components, data flow, and how to add
a new price source, see [`docs/architecture.md`](docs/architecture.md).

## Quick start (Docker Compose)

```bash
git clone https://github.com/naumanmoiz/AM4-Fuel-CO2-Prices.git
cd AM4-Fuel-CO2-Prices/deploy
cp .env.example .env
$EDITOR .env                      # paste your DISCORD_TOKEN at minimum
docker compose up -d --build
docker compose logs -f am4bot
```

You should see:

```
... store ready at /data/prices.db
... price source: null
... loaded cog: am4bot.cogs.fuel
... loaded cog: am4bot.cogs.co2
... loaded cog: am4bot.cogs.admin
... loaded cog: am4bot.cogs.poller
... logged in as <bot-name> (id=...)
... synced N commands to guild <id>          (or "globally")
```

The SQLite DB lives in a named docker volume (`am4bot-data`) mounted at
`/data` inside the container, so `docker compose down && up` preserves
your price history.

## Discord developer-portal setup

1. Go to <https://discord.com/developers/applications>, click **New
   Application**, name it (e.g. `am4-prices`).
2. Open the **Bot** tab. Click **Reset Token** and copy the token into
   `DISCORD_TOKEN` in `deploy/.env`.
3. Privileged intents: **none required**. The bot only uses slash
   commands — leave Presence / Server Members / Message Content **off**.
4. Open the **Installation** tab (or **OAuth2 → URL Generator** in
   older portal layouts):
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Embed Links` (that's all)
5. Open the generated URL, pick your server, authorise.
6. (Optional but recommended for development) put your server's ID into
   `GUILD_ID` in `.env` so command updates propagate within seconds.
   Right-click your server icon in Discord → **Copy Server ID** (Developer
   Mode must be on under User Settings → Advanced).

## Environment reference

All variables live in `deploy/.env`. See `deploy/.env.example` for the
canonical list with inline docs.

| Var | Required | Default | Notes |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | yes | — | Bot token from the developer portal |
| `GUILD_ID` | no | — | Set for instant per-guild command sync |
| `DB_PATH` | no | `/data/prices.db` | Inside container |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `PRICE_SOURCE` | no | `null` | `null` or `am4help` |
| `POLL_INTERVAL` | no | `300` | Seconds between polls |
| `AM4HELP_TOKEN` | only if `am4help` | — | Sent as `x-access-token` |
| `AM4HELP_BASE_URL` | no | `https://api.am4help.com` | |
| `AM4HELP_PRICES_PATH` | no | `/prices` | Confirm with the API owner |
| `AM4HELP_FUEL_FIELD` | no | `fuel` | Dotted JSON path |
| `AM4HELP_CO2_FIELD` | no | `co2` | Dotted JSON path |
| `SUBMIT_ALLOWED_ROLES` | no | — | CSV of role IDs |
| `SUBMIT_ALLOWED_USERS` | no | — | CSV of user IDs |

If both `SUBMIT_ALLOWED_ROLES` and `SUBMIT_ALLOWED_USERS` are empty,
`/submit` falls back to **server-admin only**.

## Configuring the AM4Help adapter

The public AM4Help docs don't currently advertise a current-prices
endpoint. Once the API owner gives you the path:

1. Set `PRICE_SOURCE=am4help`, `AM4HELP_TOKEN=...`, and update
   `AM4HELP_PRICES_PATH=/your/path` in `deploy/.env`.
2. Inspect a sample response and set `AM4HELP_FUEL_FIELD` /
   `AM4HELP_CO2_FIELD` to the dotted path of each numeric value.
   Examples:
   - response `{"fuel": 480, "co2": 110}` → `AM4HELP_FUEL_FIELD=fuel`
   - response `{"data": {"fuel": {"price": 480}}}` →
     `AM4HELP_FUEL_FIELD=data.fuel.price`
   - response `{"items": [{"name": "fuel", "value": 480}, ...]}` →
     `AM4HELP_FUEL_FIELD=items.0.value`
3. `docker compose up -d --build` — the poller picks up the new env on
   restart.

If the resolver returns a non-numeric value or the request fails, a
warning is logged and the tick is skipped (the bot stays running).

## Day-2 ops

```bash
# Tail logs
docker compose -f deploy/docker-compose.yml logs -f am4bot

# Restart after editing .env
docker compose -f deploy/docker-compose.yml up -d

# Hard rebuild after a code change
docker compose -f deploy/docker-compose.yml up -d --build

# Open a sqlite shell against the live DB
docker compose -f deploy/docker-compose.yml exec am4bot \
    python -c "import sqlite3,os; \
        c=sqlite3.connect(os.environ['DB_PATH']); \
        [print(r) for r in c.execute('SELECT * FROM prices ORDER BY ts DESC LIMIT 20')]"

# Backup the DB volume to a tarball on the host
docker run --rm -v am4bot-data:/data -v "$PWD":/backup alpine \
    tar czf /backup/am4bot-data-$(date +%F).tar.gz -C /data .

# Stop / remove (volume is preserved)
docker compose -f deploy/docker-compose.yml down

# Wipe everything including price history (destructive)
docker compose -f deploy/docker-compose.yml down -v
```

For deeper procedures (restore, upgrades, DB corruption recovery, token
rotation), see [`docs/operations.md`](docs/operations.md).

## Troubleshooting

**Bot is online but slash commands don't appear.**
Global sync can take up to ~1 hour to propagate. Set `GUILD_ID` in your
`.env` and restart — guild-scoped sync is instant. If the commands still
don't show, double-check the bot was invited with both `bot` **and**
`applications.commands` scopes (the install URL from the developer
portal must include both).

**`RuntimeError: DISCORD_TOKEN is required (set it in .env)`**
The `.env` file isn't being loaded. With Docker Compose, ensure
`deploy/.env` exists (copy from `.env.example`) and that you ran
`docker compose` from inside `deploy/` (or pass `-f deploy/docker-compose.yml`).
For local dev, the file must be at the cwd you launch `am4bot` from.

**`RuntimeError: PRICE_SOURCE=am4help requires AM4HELP_TOKEN`**
You set `PRICE_SOURCE=am4help` without filling `AM4HELP_TOKEN`. Either
provide the token or revert to `PRICE_SOURCE=null` until you have it.

**`/submit` replies "You are not allowed to submit prices."**
With both `SUBMIT_ALLOWED_ROLES` and `SUBMIT_ALLOWED_USERS` empty, only
server admins can submit. Either grant yourself admin in the server, or
add your Discord user ID to `SUBMIT_ALLOWED_USERS` in `.env` and
restart.

**Logs show `am4help fetch failed: ...`**
The AM4Help endpoint returned a non-2xx response, the timeout fired, or
the JSON didn't parse. Check `AM4HELP_BASE_URL`, `AM4HELP_PRICES_PATH`,
and `AM4HELP_TOKEN`. The poller logs the exception and continues — your
existing data is unaffected.

**Logs show `am4help fuel field 'X' resolved to non-numeric: ...`**
The configured dotted path landed on a value that isn't a number.
Inspect a sample response (`curl -H "x-access-token: $TOKEN" $URL`) and
correct `AM4HELP_FUEL_FIELD` / `AM4HELP_CO2_FIELD`.

**Container restart loop.**
`docker compose logs am4bot` shows the underlying error. Most common
causes: invalid `DISCORD_TOKEN` (Discord rejects the gateway login) or
a typo'd env var that breaks `Config.from_env()`. Fix the `.env` and
`docker compose up -d`.

**`sqlite3.OperationalError: database is locked`**
Only one process should write to the DB at a time. If you opened a
sqlite shell on the host filesystem against the live DB, close it. The
bot itself uses a single connection and won't self-deadlock.

## Development without Docker

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e .
cp deploy/.env.example .env       # at repo root
$EDITOR .env                       # set DISCORD_TOKEN, DB_PATH=./prices.db
.venv/bin/am4bot
```

## Further reading

- [`docs/architecture.md`](docs/architecture.md) — component
  responsibilities, data flow, schema rationale, how to add a new
  price source adapter.
- [`docs/operations.md`](docs/operations.md) — backup / restore drills,
  upgrades, log tuning, DB recovery, token rotation.
