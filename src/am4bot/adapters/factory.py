"""Construct the configured ``PriceAdapter`` from a ``Config`` object."""

from __future__ import annotations

import logging

from ..config import Config
from .am4help import AM4HelpAdapter
from .base import PriceAdapter
from .mgtools import MGToolsAdapter
from .mock_replay import MockReplayAdapter
from .null import NullAdapter

log = logging.getLogger(__name__)


def build_adapter(config: Config) -> PriceAdapter:
    """Return the adapter selected by ``PRICE_SOURCE``.

    Validates adapter-specific requirements at construction time —
    ``am4help`` without ``AM4HELP_TOKEN`` raises so the bot fails to
    start with a clear message rather than silently logging fetch
    errors forever.
    """
    src = config.price_source.lower()
    if src == "null":
        return NullAdapter()
    if src == "am4help":
        if not config.am4help_token:
            raise RuntimeError("PRICE_SOURCE=am4help requires AM4HELP_TOKEN")
        return AM4HelpAdapter(
            token=config.am4help_token,
            base_url=config.am4help_base_url,
            prices_path=config.am4help_prices_path,
            fuel_field=config.am4help_fuel_field,
            co2_field=config.am4help_co2_field,
        )
    if src == "mock":
        log.warning(
            "PRICE_SOURCE=mock — replaying static sample data, NOT live AM4 prices. "
            "Use this only for demo/development."
        )
        return MockReplayAdapter(data_url=config.mock_data_url)
    if src == "mgtools":
        return MGToolsAdapter(
            base_url=config.mgtools_base_url,
            prices_path=config.mgtools_prices_path,
            timezone=config.mgtools_timezone,
            user_agent=config.mgtools_user_agent,
            origin=config.mgtools_origin,
            referer=config.mgtools_referer,
        )
    raise ValueError(
        f"unknown PRICE_SOURCE: {config.price_source!r} "
        "(expected 'null', 'am4help', 'mock', or 'mgtools')"
    )
