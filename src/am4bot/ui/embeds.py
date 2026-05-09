"""Discord embed builders for slash command responses.

All builders take value objects (``PriceRecord``, ``Stats``) and a
commodity / window context, and return ``discord.Embed`` instances.
They never touch the store, the adapter, or interaction state — that
keeps cog handlers easy to reason about and the embed shapes easy to
tweak in one place.

Timestamps render as ``<t:UNIX:R>`` (Discord's relative-time syntax)
so each user sees them in their own timezone.
"""

from __future__ import annotations

import discord

from .. import __version__
from ..models import Commodity, PriceRecord, Stats, Window

_TITLE: dict[Commodity, str] = {"fuel": "Fuel", "co2": "CO₂ Quota"}


def _no_data(commodity: Commodity, label: str) -> discord.Embed:
    """Placeholder embed for "no data yet" responses."""
    return discord.Embed(
        title=f"{_TITLE[commodity]} — {label}",
        description="No data available yet.",
        color=discord.Color.dark_grey(),
    )


def make_current(rec: PriceRecord | None, commodity: Commodity) -> discord.Embed:
    """Embed for ``/fuel current`` / ``/co2 current``."""
    if rec is None:
        return _no_data(commodity, "current")
    e = discord.Embed(
        title=f"{_TITLE[commodity]} — current",
        color=discord.Color.green(),
    )
    e.add_field(name="Price", value=f"{rec.price:,.2f}", inline=True)
    e.add_field(name="Updated", value=f"<t:{rec.ts}:R>", inline=True)
    e.set_footer(text=f"source: {rec.source}")
    return e


def make_best(
    rec: PriceRecord | None, commodity: Commodity, window_label: str = "24h"
) -> discord.Embed:
    """Embed for ``/fuel best`` / ``/co2 best`` (lowest price in a window)."""
    if rec is None:
        return _no_data(commodity, f"best in {window_label}")
    e = discord.Embed(
        title=f"{_TITLE[commodity]} — best ({window_label})",
        color=discord.Color.gold(),
    )
    e.add_field(name="Lowest price", value=f"{rec.price:,.2f}", inline=True)
    e.add_field(name="When", value=f"<t:{rec.ts}:R>", inline=True)
    e.set_footer(text=f"source: {rec.source}")
    return e


def make_interval(stats: Stats, commodity: Commodity, window: Window) -> discord.Embed:
    """Embed for ``/fuel interval`` / ``/co2 interval`` (min/avg/max + sample count)."""
    if stats.count == 0:
        return _no_data(commodity, f"interval {window.label}")
    e = discord.Embed(
        title=f"{_TITLE[commodity]} — last {window.label}",
        color=discord.Color.blurple(),
    )
    e.add_field(name="Min", value=f"{stats.min:,.2f}", inline=True)
    e.add_field(name="Avg", value=f"{stats.avg:,.2f}", inline=True)
    e.add_field(name="Max", value=f"{stats.max:,.2f}", inline=True)
    e.add_field(name="Samples", value=str(stats.count), inline=True)
    e.add_field(name="From", value=f"<t:{stats.window_start}:R>", inline=True)
    return e


def make_status(
    fuel: PriceRecord | None, co2: PriceRecord | None
) -> discord.Embed:
    """Embed for ``/status`` — combined latest fuel + CO2 snapshot."""
    e = discord.Embed(title="AM4 prices — status", color=discord.Color.blue())
    for commodity, rec in (("fuel", fuel), ("co2", co2)):
        if rec is None:
            e.add_field(name=_TITLE[commodity], value="no data", inline=False)
        else:
            e.add_field(
                name=_TITLE[commodity],
                value=f"{rec.price:,.2f}  ·  <t:{rec.ts}:R>  ·  `{rec.source}`",
                inline=False,
            )
    e.set_footer(text=f"am4bot v{__version__}")
    return e
