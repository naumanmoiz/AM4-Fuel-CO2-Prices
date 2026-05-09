from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Config

log = logging.getLogger(__name__)

COG_MODULES: tuple[str, ...] = (
    "am4bot.cogs.fuel",
    "am4bot.cogs.co2",
    "am4bot.cogs.admin",
    "am4bot.cogs.poller",
)


class AM4Bot(commands.Bot):
    def __init__(self, config: Config) -> None:
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.config = config

    async def setup_hook(self) -> None:
        for module in COG_MODULES:
            try:
                await self.load_extension(module)
                log.info("loaded cog: %s", module)
            except commands.ExtensionNotFound:
                log.warning("cog not found yet (skipping): %s", module)

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("logged in as %s (id=%s)", self.user, self.user.id)

        if self.config.guild_id is not None:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %d commands to guild %s", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.info("synced %d commands globally (may take up to 1h to propagate)", len(synced))
