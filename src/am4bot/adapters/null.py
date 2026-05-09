from __future__ import annotations

from ..models import PriceRecord


class NullAdapter:
    name = "null"

    async def fetch(self) -> list[PriceRecord]:
        return []

    async def aclose(self) -> None:
        return None
