"""Runtime configuration loaded from environment variables.

All settings are validated and frozen at startup. To change a value,
edit ``deploy/.env`` and restart the container — the bot does not
re-read the environment at runtime by design.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _csv_ints(raw: str) -> tuple[int, ...]:
    """Parse a comma-separated string of Discord IDs into a tuple of ints.

    Empty / whitespace segments are skipped. Used for the
    ``SUBMIT_ALLOWED_*`` env vars.
    """
    return tuple(int(x) for x in (p.strip() for p in raw.split(",")) if x)


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable bag of all runtime settings. Build via :meth:`from_env`."""
    discord_token: str
    guild_id: int | None
    db_path: str
    log_level: str
    price_source: str
    poll_interval: int
    am4help_token: str | None
    am4help_base_url: str
    am4help_prices_path: str
    am4help_fuel_field: str
    am4help_co2_field: str
    mock_data_url: str
    submit_allowed_roles: tuple[int, ...] = field(default_factory=tuple)
    submit_allowed_users: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "Config":
        """Read environment (loading ``.env`` if present) and build a Config.

        Raises ``RuntimeError`` if ``DISCORD_TOKEN`` is missing — that's
        always required and there's no sensible default. Adapter-specific
        validation (e.g. requiring ``AM4HELP_TOKEN`` when
        ``PRICE_SOURCE=am4help``) happens in
        :func:`am4bot.adapters.factory.build_adapter`.
        """
        load_dotenv()
        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is required (set it in .env)")

        guild_raw = os.environ.get("GUILD_ID", "").strip()
        guild_id = int(guild_raw) if guild_raw else None

        return cls(
            discord_token=token,
            guild_id=guild_id,
            db_path=os.environ.get("DB_PATH", "/data/prices.db"),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            price_source=os.environ.get("PRICE_SOURCE", "null").lower(),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "300")),
            am4help_token=os.environ.get("AM4HELP_TOKEN") or None,
            am4help_base_url=os.environ.get("AM4HELP_BASE_URL", "https://api.am4help.com"),
            am4help_prices_path=os.environ.get("AM4HELP_PRICES_PATH", "/prices"),
            am4help_fuel_field=os.environ.get("AM4HELP_FUEL_FIELD", "fuel"),
            am4help_co2_field=os.environ.get("AM4HELP_CO2_FIELD", "co2"),
            mock_data_url=os.environ.get(
                "MOCK_DATA_URL",
                "https://raw.githubusercontent.com/theheuman/am4-helper/"
                "main/src/assets/resource-prices.json",
            ),
            submit_allowed_roles=_csv_ints(os.environ.get("SUBMIT_ALLOWED_ROLES", "")),
            submit_allowed_users=_csv_ints(os.environ.get("SUBMIT_ALLOWED_USERS", "")),
        )
