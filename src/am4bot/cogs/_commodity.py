"""Shared command-group factory for ``/fuel`` and ``/co2``.

Every subcommand returns combined fuel + CO2 output in a single embed.
The two groups exist for discoverability but produce identical
responses — typing ``/fuel best`` is the same as ``/co2 best``.

Data semantics (post forecast-redesign):

- ``current`` : latest *observed* prices from the store (what we
  actually paid attention to most recently). Always available.
- ``best``    : top 5 lowest *upcoming* slots, sorted by price.
  Forecast-based — falls back to "no forecast" message if the
  configured price source doesn't publish forecasts.
- ``interval``: min/avg/max of *upcoming* slots in the chosen window.
  Forecast-based — same fallback as ``best``.

The historical/observed view of best and interval was removed in
favour of forecast-driven answers, because that's what's actionable
("when should I buy fuel next?") rather than retrospective.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..models import Commodity, PriceRecord, Stats, Window
from ..ui import embeds

if TYPE_CHECKING:
    from ..adapters.base import PriceAdapter
    from ..store import Store

_WINDOW_CHOICES = [app_commands.Choice(name=w.label, value=w.label) for w in Window]
_BEST_TOP_N = 5


def _store(interaction: discord.Interaction) -> "Store":
    return interaction.client.store  # type: ignore[attr-defined]


def _adapter(interaction: discord.Interaction) -> "PriceAdapter":
    return interaction.client.adapter  # type: ignore[attr-defined]


def _split_by_commodity(
    records: list[PriceRecord],
) -> tuple[list[PriceRecord], list[PriceRecord]]:
    fuel = [r for r in records if r.commodity == "fuel"]
    co2 = [r for r in records if r.commodity == "co2"]
    return fuel, co2


def _stats_from(
    records: list[PriceRecord], window_start: int, window_end: int
) -> Stats:
    if not records:
        return Stats(
            min=0.0, avg=0.0, max=0.0, count=0,
            window_start=window_start, window_end=window_end,
        )
    prices = [r.price for r in records]
    return Stats(
        min=min(prices),
        avg=sum(prices) / len(prices),
        max=max(prices),
        count=len(prices),
        window_start=window_start,
        window_end=window_end,
    )


def make_commodity_group(name: str, description: str) -> app_commands.Group:
    group = app_commands.Group(name=name, description=description)

    @group.command(name="current", description="Latest fuel and CO2 prices")
    async def _current(interaction: discord.Interaction) -> None:
        store = _store(interaction)
        fuel = await store.get_latest("fuel")
        co2 = await store.get_latest("co2")
        await interaction.response.send_message(
            embed=embeds.make_combined_current(fuel, co2)
        )

    @group.command(
        name="best",
        description=f"Top {_BEST_TOP_N} cheapest upcoming forecast slots",
    )
    async def _best(interaction: discord.Interaction) -> None:
        forecast = await _adapter(interaction).fetch_forecast()
        fuel_recs, co2_recs = _split_by_commodity(forecast)
        # Sort ascending by price; tiebreak by earliest time so user gets
        # the soonest opportunity at the same price first.
        fuel_top = sorted(fuel_recs, key=lambda r: (r.price, r.ts))[:_BEST_TOP_N]
        co2_top = sorted(co2_recs, key=lambda r: (r.price, r.ts))[:_BEST_TOP_N]
        await interaction.response.send_message(
            embed=embeds.make_combined_best_forecast(
                fuel_top, co2_top, top_n=_BEST_TOP_N
            )
        )

    @group.command(
        name="interval",
        description="min/avg/max of upcoming forecast over a window",
    )
    @app_commands.describe(interval="Window size into the future")
    @app_commands.choices(interval=_WINDOW_CHOICES)
    async def _interval(
        interaction: discord.Interaction, interval: app_commands.Choice[str]
    ) -> None:
        win = Window.from_label(interval.value)
        now = int(time.time())
        cutoff = now + win.seconds
        forecast = await _adapter(interaction).fetch_forecast()
        fuel_recs, co2_recs = _split_by_commodity(forecast)
        fuel_in_window = [r for r in fuel_recs if r.ts <= cutoff]
        co2_in_window = [r for r in co2_recs if r.ts <= cutoff]
        fuel_stats = _stats_from(fuel_in_window, now, cutoff)
        co2_stats = _stats_from(co2_in_window, now, cutoff)
        await interaction.response.send_message(
            embed=embeds.make_combined_interval_forecast(fuel_stats, co2_stats, win)
        )

    return group
