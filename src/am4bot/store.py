"""SQLite-backed price store.

A single :class:`Store` instance is owned by the bot and shared between
the slash command cogs and the background poller. Writes are
deduplicated via :meth:`Store.insert_if_changed` so the table only
records *price changes*, not every poll tick.
"""

from __future__ import annotations

import os

import aiosqlite

from .models import Commodity, PriceRecord, Stats

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    commodity TEXT    NOT NULL CHECK (commodity IN ('fuel', 'co2')),
    price     REAL    NOT NULL,
    ts        INTEGER NOT NULL,
    source    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prices_commodity_ts
    ON prices (commodity, ts DESC);
"""


class Store:
    """Async SQLite price store. Holds a single connection for the
    process lifetime; not safe to share across processes."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the connection and create the schema if needed.

        The parent directory is created on demand so an empty docker
        volume mount works on first start.
        """
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def aclose(self) -> None:
        """Close the underlying connection. Safe to call multiple times."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not initialized; call init() first")
        return self._db

    async def insert_if_changed(self, rec: PriceRecord) -> bool:
        """Insert ``rec`` only if its price differs from the latest known
        price for that commodity. Returns True when a new row was
        written, False when the record was a duplicate and skipped.

        This is the dedup key for the entire poller — without it the
        DB would grow by one row per tick regardless of price change.
        """
        latest = await self.get_latest(rec.commodity)
        if latest is not None and latest.price == rec.price:
            return False
        await self._conn.execute(
            "INSERT INTO prices (commodity, price, ts, source) VALUES (?, ?, ?, ?)",
            (rec.commodity, rec.price, rec.ts, rec.source),
        )
        await self._conn.commit()
        return True

    async def get_latest(self, commodity: Commodity) -> PriceRecord | None:
        """Return the most recently recorded price for ``commodity``, or
        None if the table has no rows for it yet."""
        async with self._conn.execute(
            "SELECT commodity, price, ts, source FROM prices "
            "WHERE commodity = ? ORDER BY ts DESC LIMIT 1",
            (commodity,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return PriceRecord(commodity=row[0], price=row[1], ts=row[2], source=row[3])

    async def get_best_in_window(
        self, commodity: Commodity, since_ts: int
    ) -> PriceRecord | None:
        """Return the lowest-priced record at or after ``since_ts``.

        Ties are broken by recency (most recent first). Returns None
        when no rows fall in the window.
        """
        async with self._conn.execute(
            "SELECT commodity, price, ts, source FROM prices "
            "WHERE commodity = ? AND ts >= ? "
            "ORDER BY price ASC, ts DESC LIMIT 1",
            (commodity, since_ts),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return PriceRecord(commodity=row[0], price=row[1], ts=row[2], source=row[3])

    async def get_top_n_in_window(
        self, commodity: Commodity, since_ts: int, n: int
    ) -> list[PriceRecord]:
        """Return up to ``n`` rows with the lowest prices in the window.

        Sorted ascending by price; ties broken by recency. Used by
        ``/fuel best`` to show the top-N lowest snapshots in the last
        24h, not just the single minimum.
        """
        async with self._conn.execute(
            "SELECT commodity, price, ts, source FROM prices "
            "WHERE commodity = ? AND ts >= ? "
            "ORDER BY price ASC, ts DESC LIMIT ?",
            (commodity, since_ts, n),
        ) as cur:
            rows = await cur.fetchall()
        return [
            PriceRecord(commodity=r[0], price=r[1], ts=r[2], source=r[3])
            for r in rows
        ]

    async def get_stats_in_window(
        self, commodity: Commodity, since_ts: int, until_ts: int
    ) -> Stats:
        """Return min/avg/max/count for ``commodity`` in ``[since_ts, until_ts]``.

        ``Stats.count == 0`` when no rows match; the other fields are
        zeroed in that case so callers can render a "no data" embed
        without a separate None check.
        """
        async with self._conn.execute(
            "SELECT MIN(price), AVG(price), MAX(price), COUNT(*) "
            "FROM prices WHERE commodity = ? AND ts >= ? AND ts <= ?",
            (commodity, since_ts, until_ts),
        ) as cur:
            row = await cur.fetchone()
        if row is None or row[3] == 0:
            return Stats(
                min=0.0, avg=0.0, max=0.0, count=0,
                window_start=since_ts, window_end=until_ts,
            )
        return Stats(
            min=float(row[0]),
            avg=float(row[1]),
            max=float(row[2]),
            count=int(row[3]),
            window_start=since_ts,
            window_end=until_ts,
        )
