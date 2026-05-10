"""Adapter Protocol — the contract every price source implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import PriceRecord


@runtime_checkable
class PriceAdapter(Protocol):
    """A pluggable price source.

    The poller treats every source identically: tick, call ``fetch``,
    iterate the returned records into the store.

    For *forecast-aware* sources, ``fetch_forecast`` returns records
    with timestamps in the future. Adapters whose upstream doesn't
    publish forecasts return ``[]`` from ``fetch_forecast``. Cog
    handlers fall back gracefully (show "no forecast data") when
    that's the case.

    Both methods should not raise. Network/parse errors should be
    logged and turned into an empty list. ``aclose`` releases any
    held resources (HTTP sessions, file handles); it's called by
    ``AM4Bot.close()`` on shutdown.
    """

    name: str
    """Short identifier stored in ``PriceRecord.source`` for audit trails."""

    async def fetch(self) -> list[PriceRecord]:
        """Pull current prices. Empty list is valid (no data right now)."""
        ...

    async def fetch_forecast(self) -> list[PriceRecord]:
        """Pull upcoming/forecasted prices.

        Each returned record's ``ts`` is in the future (Unix seconds).
        Adapters without forecast support return ``[]``.
        """
        ...

    async def aclose(self) -> None:
        """Release any held resources. Idempotent."""
        ...
