"""Bot subclass that owns the Store and Adapter and loads the cogs.

The bot is a thin shell: it wires up runtime dependencies, loads cogs,
and handles command-tree sync. All commodity logic lives in the cogs
and supporting modules.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .adapters.base import PriceAdapter
from .adapters.factory import build_adapter
from .config import Config
from .store import Store

log = logging.getLogger(__name__)

COG_MODULES: tuple[str, ...] = (
    "am4bot.cogs.fuel",
    "am4bot.cogs.co2",
    "am4bot.cogs.admin",
    "am4bot.cogs.poller",
)


class AM4Bot(commands.Bot):
    """``commands.Bot`` subclass with the runtime dependencies attached.

    Cogs reach the store and adapter via ``bot.store`` / ``bot.adapter``
    rather than receiving them as constructor arguments — that's
    discord.py's idiomatic pattern and keeps cog ``setup`` functions
    one-liners.
    """

    def __init__(self, config: Config) -> None:
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.config = config
        self.store = Store(config.db_path)
        self.adapter: PriceAdapter = build_adapter(config)

    async def setup_hook(self) -> None:
        """discord.py lifecycle hook — runs once before the gateway connects.

        Initialises the DB and loads all cogs. Errors here propagate and
        prevent the bot from starting, which is the right behaviour:
        we'd rather fail loudly at boot than connect to Discord with a
        broken store.
        """
        await self.store.init()
        log.info("store ready at %s", self.config.db_path)
        log.info("price source: %s", self.adapter.name)
        for module in COG_MODULES:
            await self.load_extension(module)
            log.info("loaded cog: %s", module)

    async def on_ready(self) -> None:
        """Sync the application command tree once the gateway is ready.

        With ``GUILD_ID`` set, commands sync to that single guild and
        appear within seconds. Without it they sync globally, which can
        take up to ~1 hour to propagate across all servers.
        """
        assert self.user is not None
        log.info("logged in as %s (id=%s)", self.user, self.user.id)

        if self.config.guild_id is not None:
            guild = discord.Object(id=self.config.guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("synced %d commands to guild %s", len(synced), self.config.guild_id)
        else:
            synced = await self.tree.sync()
            log.info(
                "synced %d commands globally (may take up to 1h to propagate)",
                len(synced),
            )

    async def close(self) -> None:
        """Release adapter resources and close the DB before disconnecting.

        We close in the order adapter → store → super so a hanging
        aiohttp session doesn't block DB cleanup, and the gateway close
        always happens even if earlier cleanup raises.
        """
        try:
            await self.adapter.aclose()
        finally:
            try:
                await self.store.aclose()
            finally:
                await super().close()
