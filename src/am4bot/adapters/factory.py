from __future__ import annotations

from ..config import Config
from .am4help import AM4HelpAdapter
from .base import PriceAdapter
from .null import NullAdapter


def build_adapter(config: Config) -> PriceAdapter:
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
    raise ValueError(
        f"unknown PRICE_SOURCE: {config.price_source!r} (expected 'null' or 'am4help')"
    )
