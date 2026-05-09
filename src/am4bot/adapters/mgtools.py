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

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
