"""Discord embed builders for slash command responses.

All builders take value objects (``PriceRecord``, ``Stats``) and a
window context, and return ``discord.Embed`` instances. They never
touch the store, the adapter, or interaction state — that keeps cog
handlers easy to reason about and the embed shapes easy to tweak in
one place.

Timestamps render as ``<t:UNIX:R>`` (Discord's relative-time syntax)
so each user sees them in their own timezone, AND past vs future
timestamps are formatted differently ("5 minutes ago" vs "in 4 hours")
without us having to do anything special.

The ``/fuel`` and ``/co2`` slash command groups both produce
*combined* embeds — every response shows fuel + CO2 side by side
regardless of which group the user invoked. ``current`` returns
observed prices from the DB; ``best`` and ``interval`` are forecast-
based and return empty embeds with an explanation when the configured
adapter doesn't publish forecasts. Per-commodity rendering is reserved
for the ``/submit`` confirmation, which only ever records one
commodity at a time.
"""

from __future__ import annotations

import discord

from .. import __version__
from ..models import Commodity, PriceRecord, Stats, Window

_TITLE: dict[Commodity, str] = {"fuel": "Fuel", "co2": "CO₂ Quota"}


def make_current(rec: PriceRecord | None, commodity: Commodity) -> discord.Embed:
    """Single-commodity embed used by ``/submit`` to confirm a write."""
    if rec is None:
        return discord.Embed(
            title=f"{_TITLE[commodity]} — current",
            description="No data available yet.",
            color=discord.Color.dark_grey(),
        )
    e = discord.Embed(
        title=f"{_TITLE[commodity]} — current",
        color=discord.Color.green(),
    )
    e.add_field(name="Price", value=f"{rec.price:,.2f}", inline=True)
    e.add_field(name="Updated", value=f"<t:{rec.ts}:R>", inline=True)
    e.set_footer(text=f"source: {rec.source}")
    return e


def _commodity_field(rec: PriceRecord | None) -> str:
    if rec is None:
        return "no data"
    return f"**{rec.price:,.2f}**\n<t:{rec.ts}:R>"


def make_combined_current(
    fuel: PriceRecord | None, co2: PriceRecord | None
) -> discord.Embed:
    """Combined current-price embed for ``/fuel current`` / ``/co2 current``."""
    e = discord.Embed(title="AM4 prices — current", color=discord.Color.green())
    e.add_field(name="Fuel", value=_commodity_field(fuel), inline=True)
    e.add_field(name="CO₂ Quota", value=_commodity_field(co2), inline=True)
    src = (fuel or co2).source if (fuel or co2) else None
    if src:
        e.set_footer(text=f"source: {src}")
    return e


def _top_n_field(records: list[PriceRecord]) -> str:
    if not records:
        return "no data"
    # Right-align prices in a fixed-width column so the list reads cleanly
    width = max(len(f"{r.price:,.2f}") for r in records)
    lines = [f"`{r.price:>{width},.2f}`  ·  <t:{r.ts}:R>" for r in records]
    return "\n".join(lines)


def make_combined_best_forecast(
    fuel_top: list[PriceRecord],
    co2_top: list[PriceRecord],
    top_n: int = 5,
) -> discord.Embed:
    """Top N cheapest upcoming forecast slots for fuel and CO2.

    Records' timestamps are in the future, so Discord's <t:UNIX:R>
    syntax renders them as 'in 30 minutes', 'in 4 hours', etc. — which
    is exactly what the user wants for planning ("when's the next dip?").
    """
    e = discord.Embed(
        title=f"AM4 prices — {top_n} cheapest upcoming",
        color=discord.Color.gold(),
    )
    if not fuel_top and not co2_top:
        e.description = (
            "No forecast data available. Forecasts require "
            "`PRICE_SOURCE=mgtools` or `PRICE_SOURCE=mock`."
        )
        return e
    e.add_field(name="Fuel", value=_top_n_field(fuel_top), inline=True)
    e.add_field(name="CO₂ Quota", value=_top_n_field(co2_top), inline=True)
    return e


def _stats_field(stats: Stats) -> str:
    if stats.count == 0:
        return "no data"
    return (
        f"min **{stats.min:,.2f}**\n"
        f"avg {stats.avg:,.2f}\n"
        f"max {stats.max:,.2f}\n"
        f"({stats.count} samples)"
    )


def make_combined_interval_forecast(
    fuel_stats: Stats, co2_stats: Stats, window: Window
) -> discord.Embed:
    """Forecast min/avg/max for fuel and CO2 over an upcoming window."""
    e = discord.Embed(
        title=f"AM4 prices — next {window.label} forecast",
        color=discord.Color.blurple(),
    )
    if fuel_stats.count == 0 and co2_stats.count == 0:
        e.description = (
            "No forecast data available for this window. Forecasts "
            "require `PRICE_SOURCE=mgtools` or `PRICE_SOURCE=mock`. "
            "mgtools only publishes forecasts to end of day, so a 7d "
            "window may return empty late in the day."
        )
        return e
    e.add_field(name="Fuel", value=_stats_field(fuel_stats), inline=True)
    e.add_field(name="CO₂ Quota", value=_stats_field(co2_stats), inline=True)
    e.add_field(
        name="Window",
        value=f"until <t:{fuel_stats.window_end}:R>",
        inline=False,
    )
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
