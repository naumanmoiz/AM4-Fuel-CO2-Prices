"""Shared command-group factory for ``/fuel`` and ``/co2``.

Both groups now produce *combined* output — every subcommand returns
fuel + CO2 side by side. The two groups exist for discoverability
(typing ``/`` shows both as autocomplete hints) but are functionally
equivalent. The ``commodity`` argument that previously bound a group
to one commodity is gone; the factory just takes a ``name`` and
``description``.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..models import Window
from ..ui import embeds

if TYPE_CHECKING:
    from ..store import Store

_WINDOW_CHOICES = [app_commands.Choice(name=w.label, value=w.label) for w in Window]
_BEST_TOP_N = 5
_BEST_WINDOW = Window.H24


def _store(interaction: discord.Interaction) -> "Store":
    """Reach the bot's store from inside an interaction handler."""
    return interaction.client.store  # type: ignore[attr-defined]


def make_commodity_group(name: str, description: str) -> app_commands.Group:
    """Build a slash command group with combined-output current/best/interval."""
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
        description=f"Top {_BEST_TOP_N} lowest fuel and CO2 prices in the last 24h",
    )
    async def _best(interaction: discord.Interaction) -> None:
        store = _store(interaction)
        since = int(time.time()) - _BEST_WINDOW.seconds
        fuel_top = await store.get_top_n_in_window("fuel", since, _BEST_TOP_N)
        co2_top = await store.get_top_n_in_window("co2", since, _BEST_TOP_N)
        await interaction.response.send_message(
            embed=embeds.make_combined_best(
                fuel_top, co2_top, _BEST_WINDOW.label, _BEST_TOP_N
            )
        )

    @group.command(
        name="interval", description="min/avg/max for fuel and CO2 over a window"
    )
    @app_commands.describe(interval="Time window")
    @app_commands.choices(interval=_WINDOW_CHOICES)
    async def _interval(
        interaction: discord.Interaction, interval: app_commands.Choice[str]
    ) -> None:
        store = _store(interaction)
        win = Window.from_label(interval.value)
        now = int(time.time())
        fuel_stats = await store.get_stats_in_window("fuel", now - win.seconds, now)
        co2_stats = await store.get_stats_in_window("co2", now - win.seconds, now)
        await interaction.response.send_message(
            embed=embeds.make_combined_interval(fuel_stats, co2_stats, win)
        )

    return group
