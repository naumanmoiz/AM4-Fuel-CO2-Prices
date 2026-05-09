"""Adapter Protocol — the contract every price source implements."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import PriceRecord


@runtime_checkable
class PriceAdapter(Protocol):
    """A pluggable price source.

    The poller treats every source identically: tick, call ``fetch``,
    iterate the returned records into the store. The two practical
    requirements:

    1. ``fetch`` should not raise. Network/parse errors should be logged
       and turned into an empty list. Raising would crash the
       ``tasks.loop`` (it would auto-restart, but logs would be noisier
       than necessary).
    2. ``aclose`` should release any held resources (HTTP sessions,
       file handles). It's called by ``AM4Bot.close()`` on shutdown.
    """

    name: str
    """Short identifier stored in ``PriceRecord.source`` for audit trails."""

    async def fetch(self) -> list[PriceRecord]:
        """Pull current prices. Empty list is valid (no data right now)."""
        ...

    async def aclose(self) -> None:
        """Release any held resources. Idempotent."""
        ...
