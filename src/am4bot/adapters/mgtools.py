"""Adapter for the mgtools.cloud public predict endpoint.

POSTs to https://api.mgtools.cloud/v1/data-predict-v2 with a JSON body
of ``{"timezone": "<tz>"}`` and parses the returned 48-slot half-hourly
forecast. Exactly one slot's ``time`` field is prefixed with ``"-> "``;
that's the one mgtools considers current. Only that slot is recorded —
the other 47 are forecasts and would skew /fuel best if ingested.

No auth, no API key. The endpoint enforces only CORS-style Origin and
Referer checks at the WAF, plus a browser-style User-Agent. The
defaults below match what mgtools.cloud's own SPA sends.
"""

from __future__ import annotations

import json
import logging
import time

import aiohttp

from ..models import PriceRecord

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0"
)


class MGToolsAdapter:
    """POST-based adapter for mgtools.cloud's data-predict-v2 endpoint."""

    name = "mgtools"

    def __init__(
        self,
        base_url: str,
        prices_path: str,
        timezone: str,
        user_agent: str = DEFAULT_USER_AGENT,
        origin: str = "https://mgtools.cloud",
        referer: str = "https://mgtools.cloud/",
        timeout: float = 15.0,
    ) -> None:
        self._url = base_url.rstrip("/") + "/" + prices_path.lstrip("/")
        self._body = json.dumps({"timezone": timezone}).encode("utf-8")
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": origin,
            "Referer": referer,
        }
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def fetch(self) -> list[PriceRecord]:
        """POST the predict request and return only the slot marked '-> '.

        Returns an empty list (and logs a warning) on network errors,
        non-2xx responses, malformed JSON, mgtools maintenance windows,
        or a missing/invalid current-slot marker.
        """
        try:
            session = await self._get_session()
            async with session.post(
                self._url, data=self._body, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except Exception as exc:
            log.warning("mgtools fetch failed: %s", exc)
            return []

        if not isinstance(payload, dict):
            log.warning(
                "mgtools: unexpected payload type %s; expected object",
                type(payload).__name__,
            )
            return []

        if payload.get("maintenance"):
            log.info("mgtools: API reports maintenance, skipping tick")
            return []

        data = payload.get("data")
        if not isinstance(data, list):
            log.warning("mgtools: response missing 'data' array")
            return []

        current = None
        for entry in data:
            if not isinstance(entry, dict):
                continue
            time_str = entry.get("time")
            if isinstance(time_str, str) and time_str.lstrip().startswith("->"):
                current = entry
                break

        if current is None:
            log.warning(
                "mgtools: no entry marked '->' in data array (%d entries); "
                "cannot determine current slot",
                len(data),
            )
            return []

        try:
            fuel = float(current["fuel"])
            co2 = float(current["co2"])
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("mgtools: current entry has invalid fuel/co2: %s", exc)
            return []

        ts = int(time.time())
        return [
            PriceRecord(commodity="fuel", price=fuel, ts=ts, source=self.name),
            PriceRecord(commodity="co2", price=co2, ts=ts, source=self.name),
        ]

    async def fetch_forecast(self) -> list[PriceRecord]:
        """Return the next 24h of forecasted slots.

        mgtools' response is a 48-element cyclical array — entries
        before the '->' marker represent the same slots one day in the
        future (the model assumes the daily pattern repeats). So we
        rotate the array to ``[entries_after_marker] + [entries_before_marker]``
        and emit all 47 non-marker entries as future records, where slot
        ``k`` (1-indexed) is exactly ``30 * k`` minutes from now.

        This gives a full 24-hour forecast horizon regardless of when
        the bot is queried, instead of trailing off late in the day.
        """
        try:
            session = await self._get_session()
            async with session.post(
                self._url, data=self._body, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                payload = await resp.json(content_type=None)
        except Exception as exc:
            log.warning("mgtools forecast fetch failed: %s", exc)
            return []

        if not isinstance(payload, dict) or payload.get("maintenance"):
            return []
        data = payload.get("data")
        if not isinstance(data, list):
            return []

        marker_idx: int | None = None
        for i, entry in enumerate(data):
            if not isinstance(entry, dict):
                continue
            time_str = entry.get("time")
            if isinstance(time_str, str) and time_str.lstrip().startswith("->"):
                marker_idx = i
                break
        if marker_idx is None:
            return []

        # Rotate: entries after marker = today's remaining, entries before
        # marker = same slots in the next daily cycle (tomorrow). Together
        # they cover the next 24h.
        rotated = list(data[marker_idx + 1 :]) + list(data[:marker_idx])

        ts_now = int(time.time())
        records: list[PriceRecord] = []
        for k, entry in enumerate(rotated, start=1):
            if not isinstance(entry, dict):
                continue
            try:
                fuel = float(entry["fuel"])
                co2 = float(entry["co2"])
            except (KeyError, TypeError, ValueError):
                continue
            ts_future = ts_now + 30 * 60 * k
            records.append(
                PriceRecord(commodity="fuel", price=fuel, ts=ts_future, source=self.name)
            )
            records.append(
                PriceRecord(commodity="co2", price=co2, ts=ts_future, source=self.name)
            )
        return records

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
