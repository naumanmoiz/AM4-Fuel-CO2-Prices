"""Demo / placeholder price source.

Loads a public JSON dataset of AM4 fuel and CO2 readings (from
theheuman/am4-helper, which ships them as static demo data in its
Ionic app), then on every poll tick maps "now" to the closest matching
sample by day-of-month and time-of-day.

Use case: bootstrapping the bot before a real upstream (AM4Help token
or the official AM4 API key) is available, so /fuel current,
/fuel best, and /fuel interval all return realistic-shaped values.

The data is *not* live AM4 prices. The ``source`` field on every
record is the literal string ``"mock"`` so it's obvious in /status,
embed footers, and the SQL audit trail that the values are synthetic.
"""

from __future__ import annotations

import bisect
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from ..models import PriceRecord

log = logging.getLogger(__name__)

_TIME_FMT_HINTS = ("T", " ")


def _parse_time_of_day(raw: str) -> int | None:
    """Parse the ``time`` field's hour:minute:second into seconds-of-day.

    The mock dataset's ``time`` strings come in two shapes:
      - ``"00:30:00.000Z"`` — bare time-of-day with millis + Z suffix
      - ``"2024-01-01T00:30:00.000Z"`` — full ISO 8601

    Both should produce the same seconds-of-day. Returns ``None`` if
    the string can't be parsed; the caller drops bad rows.
    """
    s = raw.strip().rstrip("Z")
    # Strip any leading date portion if present
    for hint in _TIME_FMT_HINTS:
        if hint in s:
            s = s.split(hint, 1)[1]
            break
    # Now s should look like "HH:MM:SS" or "HH:MM:SS.fff"
    s = s.split(".", 1)[0]
    parts = s.split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, sec = (int(p) for p in parts)
    except ValueError:
        return None
    if not (0 <= h < 24 and 0 <= m < 60 and 0 <= sec < 60):
        return None
    return h * 3600 + m * 60 + sec


class MockReplayAdapter:
    """Replay-from-static-dataset adapter for demo / development use."""

    name = "mock"

    def __init__(self, data_url: str, timeout: float = 15.0) -> None:
        self._data_url = data_url
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        # Per-day index: list of (sec_of_day, fuel, co2) tuples sorted by sec_of_day.
        # _by_day[day_int] = sorted_samples_for_that_day
        self._by_day: dict[int, list[tuple[int, float, float]]] = {}
        self._available_days: list[int] = []
        self._loaded = False

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)

        try:
            async with self._session.get(self._data_url) as resp:
                resp.raise_for_status()
                raw = await resp.json(content_type=None)
        except Exception as exc:
            log.warning("mock data load failed (%s); will retry next tick", exc)
            return

        # Two known shapes:
        #   {"oddMonth": {"1": [...], "3": [...], ...}}    (root resource-prices.json)
        #   {"1": [...], "2": [...], ...}                  (src/assets/resource-prices.json)
        days = raw
        if isinstance(raw, dict) and "oddMonth" in raw and isinstance(raw["oddMonth"], dict):
            days = raw["oddMonth"]
        if not isinstance(days, dict):
            log.warning("mock data has unexpected top-level shape: %s", type(raw).__name__)
            self._loaded = True
            return

        total = 0
        for day_key, entries in days.items():
            try:
                day_int = int(day_key)
            except (ValueError, TypeError):
                continue
            if not isinstance(entries, list):
                continue
            samples: list[tuple[int, float, float]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                sec = _parse_time_of_day(entry.get("time", ""))
                if sec is None:
                    continue
                try:
                    fuel = float(entry["fuel"])
                    co2 = float(entry["co2"])
                except (KeyError, TypeError, ValueError):
                    continue
                samples.append((sec, fuel, co2))
            if samples:
                samples.sort(key=lambda x: x[0])
                self._by_day[day_int] = samples
                total += len(samples)

        self._available_days = sorted(self._by_day.keys())
        self._loaded = True
        if total == 0:
            log.warning("mock dataset parsed to 0 usable samples")
        else:
            log.info(
                "mock dataset loaded: %d samples across %d days",
                total, len(self._available_days),
            )

    def _sample_for_now(self) -> tuple[float, float] | None:
        if not self._available_days:
            return None
        now = datetime.now(timezone.utc)
        # Pick the available day closest to today's day-of-month, wrapping if needed
        # so all real days resolve to a sample bucket.
        idx = (now.day - 1) % len(self._available_days)
        day_int = self._available_days[idx]
        samples = self._by_day[day_int]
        sec_now = now.hour * 3600 + now.minute * 60 + now.second
        keys = [s[0] for s in samples]
        i = bisect.bisect_left(keys, sec_now)
        candidates: list[tuple[int, float, float]] = []
        if i > 0:
            candidates.append(samples[i - 1])
        if i < len(samples):
            candidates.append(samples[i])
        if not candidates:
            return None
        chosen = min(candidates, key=lambda s: abs(s[0] - sec_now))
        return chosen[1], chosen[2]

    async def fetch(self) -> list[PriceRecord]:
        """Return one synthetic fuel + one synthetic co2 record for "now"."""
        await self._ensure_loaded()
        sample = self._sample_for_now()
        if sample is None:
            return []
        fuel, co2 = sample
        ts = int(time.time())
        return [
            PriceRecord(commodity="fuel", price=fuel, ts=ts, source=self.name),
            PriceRecord(commodity="co2", price=co2, ts=ts, source=self.name),
        ]

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
