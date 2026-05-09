# AM4-Fuel-CO2-Prices

Private Discord bot that tracks Airline Manager 4 fuel and CO₂ quota prices
and exposes them via slash commands. Designed to run as a Docker container
on a Linux VM (home lab / Proxmox).

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
relative times in their own timezone.

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

## Development without Docker

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e .
cp deploy/.env.example .env       # at repo root
$EDITOR .env                       # set DISCORD_TOKEN, DB_PATH=./prices.db
.venv/bin/am4bot
```
