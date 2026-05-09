from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _csv_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in (p.strip() for p in raw.split(",")) if x)


@dataclass(frozen=True, slots=True)
class Config:
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
    submit_allowed_roles: tuple[int, ...] = field(default_factory=tuple)
    submit_allowed_users: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "Config":
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
            submit_allowed_roles=_csv_ints(os.environ.get("SUBMIT_ALLOWED_ROLES", "")),
            submit_allowed_users=_csv_ints(os.environ.get("SUBMIT_ALLOWED_USERS", "")),
        )
