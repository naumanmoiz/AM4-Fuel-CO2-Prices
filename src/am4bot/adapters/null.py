"""No-op adapter: ``fetch`` always returns ``[]``.

Used when ``PRICE_SOURCE=null`` so the bot can run with only manual
``/submit`` data — useful before the upstream API is wired up.
"""

from __future__ import annotations

from ..models import PriceRecord


class NullAdapter:
    """Placeholder adapter that produces no records."""

    name = "null"

    async def fetch(self) -> list[PriceRecord]:
        return []

    async def fetch_forecast(self) -> list[PriceRecord]:
        return []

    async def aclose(self) -> None:
        return None
