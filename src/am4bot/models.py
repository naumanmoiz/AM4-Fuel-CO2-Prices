"""Value objects shared across the bot (records, stats, time windows)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, get_args

Commodity = Literal["fuel", "co2"]
"""Type alias for the two commodities tracked. The string values match the
``commodity`` column's CHECK constraint in the SQL schema."""

COMMODITIES: tuple[Commodity, ...] = get_args(Commodity)
"""Runtime tuple of commodity values, derived from the Literal."""


@dataclass(frozen=True, slots=True)
class PriceRecord:
    """A single price observation. Immutable so it can be safely shared
    between coroutines and used as a query input or query result."""

    commodity: Commodity
    price: float
    ts: int  # Unix seconds UTC
    source: str  # provenance: adapter name or ``manual:<user_id>``


@dataclass(frozen=True, slots=True)
class Stats:
    """Aggregate summary over a time window. ``count`` is 0 when no rows
    matched; the other fields are 0.0 in that case."""

    min: float
    avg: float
    max: float
    count: int
    window_start: int
    window_end: int


class Window(Enum):
    """Supported time windows for ``/fuel interval`` and ``/co2 interval``.

    Each member's value is ``(label, seconds)``. The label is what the
    user sees as a Discord choice; the seconds value is what gets
    subtracted from ``now`` when querying.
    """

    H1 = ("1h", 3_600)
    H4 = ("4h", 14_400)
    H12 = ("12h", 43_200)
    H24 = ("24h", 86_400)
    D7 = ("7d", 604_800)

    @property
    def label(self) -> str:
        """Short label shown to users (e.g. ``"24h"``)."""
        return self.value[0]

    @property
    def seconds(self) -> int:
        """Window length in seconds."""
        return self.value[1]

    @classmethod
    def from_label(cls, label: str) -> "Window":
        """Look up a Window by its user-facing label. Raises ``ValueError``
        for unknown labels (defensive — discord.py validates Choice values
        before they reach this code, so a bad label means a bug)."""
        for w in cls:
            if w.label == label:
                return w
        raise ValueError(f"unknown window label: {label!r}")
