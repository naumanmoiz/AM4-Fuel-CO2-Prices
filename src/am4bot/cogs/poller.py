"""Background poller — periodically fetches prices from the configured
adapter and records changes to the store.

When ``PRICE_SOURCE=null`` the loop still ticks but the NullAdapter
returns ``[]`` so nothing is written — there's no special "polling
disabled" code path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from discord.ext import commands, tasks

if TYPE_CHECKING:
    from ..adapters.base import PriceAdapter
    from ..store import Store

log = logging.getLogger(__name__)


class PollerCog(commands.Cog):
    """Owns the ``tasks.loop`` that drives periodic price fetches."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        interval = bot.config.poll_interval  # type: ignore[attr-defined]

        @tasks.loop(seconds=interval, reconnect=True)
        async def tick() -> None:
            await self._do_tick()

        @tick.before_loop
        async def before() -> None:
            await bot.wait_until_ready()

        @tick.error
        async def on_error(error: BaseException) -> None:
            log.exception("poller tick errored", exc_info=error)

        self.tick = tick
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    async def _do_tick(self) -> None:
        """One poll cycle: fetch from the adapter, dedup-insert each record.

        Both the fetch and per-record insert are wrapped in try/except
        so a single bad response or a transient DB error never escapes
        the loop. The next tick runs on schedule regardless.
        """
        store: "Store" = self.bot.store  # type: ignore[attr-defined]
        adapter: "PriceAdapter" = self.bot.adapter  # type: ignore[attr-defined]
        try:
            records = await adapter.fetch()
        except Exception:
            log.exception("adapter %s fetch raised", adapter.name)
            return
        for rec in records:
            try:
                if await store.insert_if_changed(rec):
                    log.info(
                        "recorded %s=%s from %s", rec.commodity, rec.price, rec.source
                    )
            except Exception:
                log.exception("failed to insert %s record", rec.commodity)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PollerCog(bot))
