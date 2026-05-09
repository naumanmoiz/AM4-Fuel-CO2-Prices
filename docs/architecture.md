# Architecture

This document explains how `am4bot` is laid out internally, how data
flows through the system, and how to extend it (e.g. add a new price
source). For installation and operations, see the project
[README](../README.md) and [`operations.md`](operations.md).

## High-level picture

```
                     Discord (Slash commands)
                              ▲
                              │
                  ┌───────────┴───────────┐
                  │       AM4Bot         │  bot.py
                  │  (commands.Bot)      │
                  └───────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐           ┌─────────┐         ┌────────────┐
   │  Cogs   │           │  Store  │         │  Adapter   │
   │ (slash) │ ◄───────► │aiosqlite│ ◄───────│ (poll src) │
   └─────────┘           └─────────┘         └────────────┘
                              │                     │
                              ▼                     ▼
                     prices.db (volume)     api.am4help.com
```

`AM4Bot` owns one `Store` instance and one `PriceAdapter` instance.
Cogs (slash commands and the background poller) reach them via
`bot.store` / `bot.adapter`.

## Module layout

```
src/am4bot/
├── __main__.py        # entry point — loads config, starts the bot
├── bot.py             # AM4Bot subclass — owns Store + Adapter, loads cogs
├── config.py          # Config dataclass + Config.from_env()
├── models.py          # PriceRecord, Stats, Window, Commodity literal
├── store.py           # aiosqlite Store
├── adapters/
│   ├── base.py        # PriceAdapter Protocol
│   ├── null.py        # NullAdapter (no-op)
│   ├── am4help.py     # AM4HelpAdapter (HTTP + dotted-path JSON)
│   ├── mgtools.py     # MGToolsAdapter (POST + arrow-marker parser)
│   ├── mock_replay.py # MockReplayAdapter (static dataset replay; demo only)
│   └── factory.py     # build_adapter(config) -> PriceAdapter
├── cogs/
│   ├── _commodity.py  # shared command-group factory
│   ├── fuel.py        # /fuel cog (10 lines)
│   ├── co2.py         # /co2 cog (10 lines)
│   ├── admin.py       # /submit, /status
│   └── poller.py      # tasks.loop calling adapter+store
└── ui/
    └── embeds.py      # discord.Embed builders
```

**One concern per file.** Cogs translate Discord interactions into
store calls and embed responses; they hold no business logic of their
own. The store knows about SQLite. Adapters know about HTTP and JSON
shape. The UI module knows about Discord embeds.

## Database schema

```sql
CREATE TABLE prices (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity TEXT    NOT NULL CHECK (commodity IN ('fuel', 'co2')),
    price     REAL    NOT NULL,
    ts        INTEGER NOT NULL,
    source    TEXT    NOT NULL
);

CREATE INDEX idx_prices_commodity_ts ON prices (commodity, ts DESC);
```

**Why one table.** Fuel and CO₂ are the same shape (a price + a
timestamp + provenance). Splitting them into separate tables would
duplicate every query. The `CHECK` constraint plus the `Commodity`
literal in Python prevent typos statically and at write time.

**Why `ts` is INTEGER (Unix seconds UTC).** Discord's `<t:UNIX:R>`
embed syntax takes Unix seconds. Storing the same representation
removes any timezone conversion at read time. INTEGER also indexes
faster than ISO strings.

**Why `source TEXT`.** It records *where* the price came from
(`am4help`, `manual:<user_id>`, future adapters) so we can audit
history and tell automated readings apart from human submissions.

**Why dedup via `insert_if_changed`.** Polling every 5 minutes for
months produces ≈100k rows even if the price barely moves. By skipping
inserts where the new price equals the latest known price, we get
*one row per price change*, which keeps the DB small and makes "best
in window" queries scan the actual transitions rather than mostly-equal
samples.

## Data flow

### Poll path (`PRICE_SOURCE=am4help`)

```
tasks.loop tick
   │
   ▼
adapter.fetch()                 ── HTTP GET base_url + prices_path
   │                               with x-access-token header
   ▼
JSON body
   │
   ▼
resolve_path(body, fuel_field)  ── dotted path walk
resolve_path(body, co2_field)
   │
   ▼
[PriceRecord(fuel,...), PriceRecord(co2,...)]
   │
   ▼
for each rec:
    store.insert_if_changed(rec)
         │
         ├─ get_latest(rec.commodity) returns same price → skip (False)
         └─ otherwise INSERT + COMMIT (True)
```

Errors at any step are logged at WARNING and turned into an empty list
or skipped insert; the loop continues on the next tick. The bot
process never exits because of a bad upstream response.

### `/submit` path

```
slash interaction
   │
   ▼
AdminCog.submit
   │
   ├─ _is_allowed?  (env allowlist or admin fallback)
   │     no → ephemeral "not allowed" reply, stop
   │
   ├─ price > 0?
   │     no → ephemeral "must be positive" reply, stop
   │
   ▼
PriceRecord(commodity, price, ts=now, source=f"manual:{user_id}")
   │
   ▼
store.insert_if_changed(rec)
   ├─ True  → reply with "current" embed
   └─ False → ephemeral "unchanged, not recorded"
```

### `/fuel current` path (read-only)

```
slash interaction
   │
   ▼
fuel group → _current handler
   │
   ▼
store.get_latest("fuel")
   │
   ▼
embeds.make_current(rec, "fuel")
   │
   ▼
interaction.response.send_message(embed=...)
```

`/fuel best`, `/fuel interval`, `/co2 …`, and `/status` are minor
variations on this — different store query, different embed builder.

## The adapter pattern

`PriceAdapter` is a `typing.Protocol` (structural typing, no
inheritance required):

```python
class PriceAdapter(Protocol):
    name: str
    async def fetch(self) -> list[PriceRecord]: ...
    async def aclose(self) -> None: ...
```

Three contracts:

1. **`fetch()` returns a list.** Empty is valid (no prices available
   right now). The poller iterates and calls `insert_if_changed` per
   record, so partial responses are fine — fuel might be missing while
   CO₂ is present, or vice versa.
2. **`fetch()` must not raise.** On error, log and return `[]`. The
   poller has its own try/except as belt-and-braces but the contract
   keeps adapter implementations honest.
3. **`aclose()` releases resources.** Called by `AM4Bot.close()` on
   shutdown so aiohttp sessions close cleanly.

### MGToolsAdapter

`mgtools.py` POSTs `{"timezone": "<tz>"}` to mgtools.cloud's
`data-predict-v2` endpoint. The response is a 48-element array of
half-hourly forecasts with one entry's `time` field prefixed with
`"-> "` to indicate the current slot. The adapter ingests **only the
marked slot** — storing the 47 future predictions would distort
`/fuel best` and `/fuel interval` answers, since those queries
implicitly assume rows reflect prices that actually occurred.

The endpoint requires no API key. WAF-side enforcement is limited to
CORS-style `Origin` and `Referer` checks plus a browser-style
`User-Agent`. All three are configurable via env vars and default to
values that match what mgtools.cloud's own SPA sends.

The adapter respects the response's `maintenance` flag (skips the
tick instead of writing stale data) and tolerates missing/malformed
markers by returning `[]` rather than raising.

### MockReplayAdapter

`mock_replay.py` is a non-network demo adapter that replays a static
JSON dataset. It exists as a documented example of "what a third
adapter looks like" and as a way to bring up the bot's UX before any
live upstream is wired up. The dataset (sourced at runtime from
`theheuman/am4-helper` by default, but any URL with the same shape
works) is loaded once on first `fetch()` and then indexed by
day-of-month and time-of-day. Each tick maps "now" to the closest
sample.

The `source` field on every record is the literal string `"mock"` so
operators can always tell synthetic data from real data when looking
at `/status`, embed footers, or the SQL audit trail. Logs a
`WARNING` at construction time so it can't be enabled silently.

### Adding a new adapter

Suppose you find a second prices source called *example*:

1. Create `src/am4bot/adapters/example.py`:

   ```python
   from ..models import PriceRecord

   class ExampleAdapter:
       name = "example"

       def __init__(self, token: str) -> None:
           self._token = token
           # init aiohttp session lazily in fetch()

       async def fetch(self) -> list[PriceRecord]:
           # ... HTTP request, parse, build PriceRecord list, log on error
           return []

       async def aclose(self) -> None:
           ...
   ```

2. Wire it into `adapters/factory.py`:

   ```python
   if src == "example":
       if not config.example_token:
           raise RuntimeError("PRICE_SOURCE=example requires EXAMPLE_TOKEN")
       return ExampleAdapter(token=config.example_token)
   ```

3. Add the new env vars to `Config` (in `config.py`) and document
   them in `deploy/.env.example`.

No other code changes — cogs, store, and `bot.py` are agnostic to
which adapter is in use.

## Cogs

discord.py organises slash commands into *cogs* (classes that group
related commands). The four cogs are:

| Cog | File | Purpose |
| --- | --- | --- |
| `FuelCog` | `cogs/fuel.py` | Registers the `/fuel` group |
| `Co2Cog` | `cogs/co2.py` | Registers the `/co2` group |
| `AdminCog` | `cogs/admin.py` | `/submit` (allowlist), `/status` |
| `PollerCog` | `cogs/poller.py` | Background `tasks.loop` calling adapter→store |

`fuel.py` and `co2.py` are intentionally thin — both just call
`make_commodity_group(...)` from `cogs/_commodity.py` and add the
returned `app_commands.Group` to the tree. The `/fuel` and `/co2`
groups have identical command shapes (`current`, `best`, `interval`),
so the entire body lives in one place.

This is why we picked a factory function over a base class: there's
nothing each commodity overrides, only the bound commodity string
differs, and the factory makes that explicit at call time.

### Why `Optional[Member]` everywhere in `/submit` checks

Slash commands are usable in DMs by default. `interaction.user` is a
`User` in DM context and a `Member` (with role info) in guild
context. The allowlist check uses `isinstance(... discord.Member)` to
reject DM submissions cleanly.

## Polling

`PollerCog` builds a `tasks.loop(seconds=POLL_INTERVAL, reconnect=True)`
in its `__init__`. `reconnect=True` means transient gateway disconnects
don't kill the loop. `before_loop` waits for `bot.wait_until_ready()`
so the first tick happens after the cog/tree are fully wired.

Because `NullAdapter.fetch()` returns `[]`, the loop is safe to run
even with `PRICE_SOURCE=null` — it ticks but no-ops. This means the
same code path handles both "no upstream API yet" and "upstream API
configured" without conditional poller wiring.

`POLL_INTERVAL` defaults to 300 (5 minutes). Lower values risk hitting
upstream rate limits; higher values delay detection of price changes.

## Configuration

`Config` is an immutable `@dataclass(frozen=True, slots=True)`. It's
loaded once at startup by `Config.from_env()` (which calls
`dotenv.load_dotenv()` first so `.env` files are honoured) and passed
into `AM4Bot.__init__`. Mutating config at runtime is intentionally
impossible — to change settings, edit `.env` and restart.

Required vars are validated at construction (`DISCORD_TOKEN`),
adapter-specific requirements are validated in `build_adapter`
(`AM4HELP_TOKEN` if `PRICE_SOURCE=am4help`). Both fail with a clear
`RuntimeError` rather than silently using empty values.
