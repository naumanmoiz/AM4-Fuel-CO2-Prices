from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..models import Commodity, Window
from ..ui import embeds

if TYPE_CHECKING:
    from ..store import Store

_WINDOW_CHOICES = [app_commands.Choice(name=w.label, value=w.label) for w in Window]


def _store(interaction: discord.Interaction) -> "Store":
    return interaction.client.store  # type: ignore[attr-defined]


def make_commodity_group(
    commodity: Commodity, name: str, description: str
) -> app_commands.Group:
    group = app_commands.Group(name=name, description=description)

    @group.command(name="current", description=f"Latest known {name} price")
    async def _current(interaction: discord.Interaction) -> None:
        rec = await _store(interaction).get_latest(commodity)
        await interaction.response.send_message(embed=embeds.make_current(rec, commodity))

    @group.command(name="best", description=f"Lowest {name} price in the last 24h")
    async def _best(interaction: discord.Interaction) -> None:
        since = int(time.time()) - Window.H24.seconds
        rec = await _store(interaction).get_best_in_window(commodity, since)
        await interaction.response.send_message(embed=embeds.make_best(rec, commodity, "24h"))

    @group.command(name="interval", description=f"min/avg/max {name} price over a window")
    @app_commands.describe(interval="Time window")
    @app_commands.choices(interval=_WINDOW_CHOICES)
    async def _interval(
        interaction: discord.Interaction, interval: app_commands.Choice[str]
    ) -> None:
        win = Window.from_label(interval.value)
        now = int(time.time())
        stats = await _store(interaction).get_stats_in_window(
            commodity, now - win.seconds, now
        )
        await interaction.response.send_message(
            embed=embeds.make_interval(stats, commodity, win)
        )

    return group
