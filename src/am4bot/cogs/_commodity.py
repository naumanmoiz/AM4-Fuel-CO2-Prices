"""Shared command-group factory for ``/fuel`` and ``/co2``.

Every subcommand returns combined fuel + CO2 output in a single embed.
The two groups exist for discoverability but produce identical
responses — typing ``/fuel best`` is the same as ``/co2 best``.

Data semantics:

- ``current`` : latest *observed* prices from the store. Always
  available regardless of price source.
- ``best``    : top 5 lowest *upcoming* forecast slots, sorted by
  price. Times shown in the viewer's local timezone via
  ``<t:UNIX:t>``.
- ``interval``: chronological *forecast timeline* over the chosen
  window — one row per upcoming half-hour slot, colour-coded by
  cheap/mid/expensive tercile. Times rendered server-side in
  ``DISPLAY_TIMEZONE`` (code blocks can't auto-localize).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..models import PriceRecord, Window
from ..ui import embeds

if TYPE_CHECKING:
    from ..adapters.base import PriceAdapter
    from ..config import Config
    from ..store import Store

_WINDOW_CHOICES = [app_commands.Choice(name=w.label, value=w.label) for w in Window]
_BEST_TOP_N = 5


def _store(interaction: discord.Interaction) -> "Store":
    return interaction.client.store  # type: ignore[attr-defined]


def _adapter(interaction: discord.Interaction) -> "PriceAdapter":
    return interaction.client.adapter  # type: ignore[attr-defined]


def _config(interaction: discord.Interaction) -> "Config":
    return interaction.client.config  # type: ignore[attr-defined]


def _split_by_commodity(
    records: list[PriceRecord],
) -> tuple[list[PriceRecord], list[PriceRecord]]:
    fuel = [r for r in records if r.commodity == "fuel"]
    co2 = [r for r in records if r.commodity == "co2"]
    return fuel, co2


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
        fuel_top = sorted(fuel_recs, key=lambda r: (r.price, r.ts))[:_BEST_TOP_N]
        co2_top = sorted(co2_recs, key=lambda r: (r.price, r.ts))[:_BEST_TOP_N]
        await interaction.response.send_message(
            embed=embeds.make_combined_best_forecast(
                fuel_top, co2_top, top_n=_BEST_TOP_N
            )
        )

    @group.command(
        name="interval",
        description="Chronological forecast timeline over the chosen window",
    )
    @app_commands.describe(interval="How far into the future to show")
    @app_commands.choices(interval=_WINDOW_CHOICES)
    async def _interval(
        interaction: discord.Interaction, interval: app_commands.Choice[str]
    ) -> None:
        win = Window.from_label(interval.value)
        now = int(time.time())
        cutoff = now + win.seconds
        forecast = await _adapter(interaction).fetch_forecast()
        fuel_recs, co2_recs = _split_by_commodity(forecast)
        fuel_in = [r for r in fuel_recs if r.ts <= cutoff]
        co2_in = [r for r in co2_recs if r.ts <= cutoff]
        await interaction.response.send_message(
            embed=embeds.make_combined_forecast_timeline(
                fuel_in, co2_in, win,
                display_timezone=_config(interaction).display_timezone,
            )
        )

    return group
