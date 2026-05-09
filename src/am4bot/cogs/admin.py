from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..models import COMMODITIES, Commodity, PriceRecord
from ..ui import embeds

if TYPE_CHECKING:
    from ..config import Config
    from ..store import Store

_COMMODITY_CHOICES = [app_commands.Choice(name=c, value=c) for c in COMMODITIES]


def _is_allowed(
    interaction: discord.Interaction,
    allowed_roles: tuple[int, ...],
    allowed_users: tuple[int, ...],
) -> bool:
    if not allowed_roles and not allowed_users:
        # admin-only fallback when no allowlist configured
        if not isinstance(interaction.user, discord.Member):
            return False
        return interaction.user.guild_permissions.administrator
    if interaction.user.id in allowed_users:
        return True
    if isinstance(interaction.user, discord.Member):
        if {r.id for r in interaction.user.roles}.intersection(allowed_roles):
            return True
    return False


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="submit", description="Manually record a fuel or CO2 price"
    )
    @app_commands.describe(commodity="Which commodity", price="Price value")
    @app_commands.choices(commodity=_COMMODITY_CHOICES)
    async def submit(
        self,
        interaction: discord.Interaction,
        commodity: app_commands.Choice[str],
        price: float,
    ) -> None:
        config: "Config" = self.bot.config  # type: ignore[attr-defined]
        if not _is_allowed(
            interaction,
            config.submit_allowed_roles,
            config.submit_allowed_users,
        ):
            await interaction.response.send_message(
                "You are not allowed to submit prices.", ephemeral=True
            )
            return
        if price <= 0:
            await interaction.response.send_message(
                "Price must be positive.", ephemeral=True
            )
            return

        store: "Store" = self.bot.store  # type: ignore[attr-defined]
        rec = PriceRecord(
            commodity=commodity.value,  # type: ignore[arg-type]
            price=float(price),
            ts=int(time.time()),
            source=f"manual:{interaction.user.id}",
        )
        inserted = await store.insert_if_changed(rec)
        if inserted:
            await interaction.response.send_message(
                embed=embeds.make_current(rec, rec.commodity)
            )
        else:
            await interaction.response.send_message(
                f"Price unchanged from latest ({rec.price:,.2f}); not recorded.",
                ephemeral=True,
            )

    @app_commands.command(
        name="status", description="Last seen prices for fuel and CO2"
    )
    async def status(self, interaction: discord.Interaction) -> None:
        store: "Store" = self.bot.store  # type: ignore[attr-defined]
        fuel = await store.get_latest("fuel")
        co2 = await store.get_latest("co2")
        await interaction.response.send_message(embed=embeds.make_status(fuel, co2))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
