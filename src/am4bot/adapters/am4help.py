from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

from ..models import PriceRecord

log = logging.getLogger(__name__)


def resolve_path(data: Any, path: str) -> Any:
    """Walk a dotted path through nested dicts/lists.

    Numeric segments index into lists. Returns None if any segment is missing
    or the structure doesn't match.
    """
    cur = data
    for segment in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list) and segment.lstrip("-").isdigit():
            idx = int(segment)
            cur = cur[idx] if -len(cur) <= idx < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(segment)
        else:
            return None
    return cur


class AM4HelpAdapter:
    name = "am4help"

    def __init__(
        self,
        token: str,
        base_url: str,
        prices_path: str,
        fuel_field: str,
        co2_field: str,
        timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._url = base_url.rstrip("/") + "/" + prices_path.lstrip("/")
        self._fuel_field = fuel_field
        self._co2_field = co2_field
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"x-access-token": self._token},
                timeout=self._timeout,
            )
        return self._session

    async def fetch(self) -> list[PriceRecord]:
        try:
            session = await self._get_session()
            async with session.get(self._url) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except Exception as exc:
            log.warning("am4help fetch failed: %s", exc)
            return []

        ts = int(time.time())
        records: list[PriceRecord] = []

        for commodity, field in (("fuel", self._fuel_field), ("co2", self._co2_field)):
            value = resolve_path(data, field)
            if isinstance(value, bool):
                # bool is a subclass of int in Python; reject explicitly
                log.warning("am4help %s field %r resolved to bool; ignoring", commodity, field)
                continue
            if isinstance(value, (int, float)):
                records.append(
                    PriceRecord(
                        commodity=commodity,  # type: ignore[arg-type]
                        price=float(value),
                        ts=ts,
                        source=self.name,
                    )
                )
            elif value is not None:
                log.warning(
                    "am4help %s field %r resolved to non-numeric: %r",
                    commodity, field, value,
                )

        return records

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
