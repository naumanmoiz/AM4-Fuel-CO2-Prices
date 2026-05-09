from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, get_args

Commodity = Literal["fuel", "co2"]
COMMODITIES: tuple[Commodity, ...] = get_args(Commodity)


@dataclass(frozen=True, slots=True)
class PriceRecord:
    commodity: Commodity
    price: float
    ts: int
    source: str


@dataclass(frozen=True, slots=True)
class Stats:
    min: float
    avg: float
    max: float
    count: int
    window_start: int
    window_end: int


class Window(Enum):
    H1 = ("1h", 3_600)
    H4 = ("4h", 14_400)
    H12 = ("12h", 43_200)
    H24 = ("24h", 86_400)
    D7 = ("7d", 604_800)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def seconds(self) -> int:
        return self.value[1]

    @classmethod
    def from_label(cls, label: str) -> "Window":
        for w in cls:
            if w.label == label:
                return w
        raise ValueError(f"unknown window label: {label!r}")
