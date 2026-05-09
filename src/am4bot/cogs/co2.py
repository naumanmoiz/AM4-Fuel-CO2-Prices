"""``/co2`` slash command group."""

from __future__ import annotations

from discord.ext import commands

from ._commodity import make_commodity_group


class Co2Cog(commands.Cog):
    """Cog wrapper around the shared commodity command group factory."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = make_commodity_group("co2", "co2", "CO₂ quota prices")
        bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Co2Cog(bot))
