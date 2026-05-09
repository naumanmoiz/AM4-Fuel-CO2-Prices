from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import PriceRecord


@runtime_checkable
class PriceAdapter(Protocol):
    name: str

    async def fetch(self) -> list[PriceRecord]: ...

    async def aclose(self) -> None: ...
