from __future__ import annotations

from discord.ext import commands

from ._commodity import make_commodity_group


class FuelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.group = make_commodity_group("fuel", "fuel", "Fuel prices")
        bot.tree.add_command(self.group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.group.name)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FuelCog(bot))
