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
    def __init__(self, path: str) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not initialized; call init() first")
        return self._db

    async def insert_if_changed(self, rec: PriceRecord) -> bool:
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

    async def get_stats_in_window(
        self, commodity: Commodity, since_ts: int, until_ts: int
    ) -> Stats:
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
