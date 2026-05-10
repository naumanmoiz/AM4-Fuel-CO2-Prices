"""Discord embed builders for slash command responses.

All builders take value objects (``PriceRecord``, ``Stats``) and a
window context, and return ``discord.Embed`` instances. They never
touch the store, the adapter, or interaction state — that keeps cog
handlers easy to reason about and the embed shapes easy to tweak in
one place.

Most timestamps render as ``<t:UNIX:R>`` (Discord's relative-time
syntax) or ``<t:UNIX:t>`` (short clock time) so each user sees them
in their own timezone. The forecast *timeline* (``/fuel interval``)
is the exception — it's a monospaced ANSI code block whose times are
formatted server-side in ``DISPLAY_TIMEZONE`` (default UTC, falls
back to ``MGTOOLS_TIMEZONE``) since code blocks are literal text and
can't auto-localize.

The ``/fuel`` and ``/co2`` slash command groups both produce
*combined* embeds — every response shows fuel + CO2 side by side
regardless of which group the user invoked. ``current`` returns
observed prices from the DB; ``best`` and ``interval`` are forecast-
based and return empty embeds with an explanation when the configured
adapter doesn't publish forecasts. Per-commodity rendering is
reserved for the ``/submit`` confirmation, which only ever records
one commodity at a time.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone

import discord

from .. import __version__
from ..models import Commodity, PriceRecord, Stats, Window

_TITLE: dict[Commodity, str] = {"fuel": "Fuel", "co2": "CO₂ Quota"}

# Discord ANSI code-block colour codes
_ANSI_RESET = "[0m"
_ANSI_GREEN = "[0;32m"   # cheap
_ANSI_RED = "[0;31m"     # expensive
_ANSI_GREY = "[0;30m"    # day-separator label

# Description hard cap is 4096; reserve a couple of hundred chars for
# the code-fence wrapper, headers, and a possible truncation notice.
_MAX_TIMELINE_BODY = 3800


def make_current(rec: PriceRecord | None, commodity: Commodity) -> discord.Embed:
    """Single-commodity embed used by ``/submit`` to confirm a write."""
    if rec is None:
        return discord.Embed(
            title=f"{_TITLE[commodity]} — current",
            description="No data available yet.",
            color=discord.Color.dark_grey(),
        )
    e = discord.Embed(
        title=f"{_TITLE[commodity]} — current",
        color=discord.Color.green(),
    )
    e.add_field(name="Price", value=f"{rec.price:,.2f}", inline=True)
    e.add_field(name="Updated", value=f"<t:{rec.ts}:R>", inline=True)
    e.set_footer(text=f"source: {rec.source}")
    return e


def _commodity_field(rec: PriceRecord | None) -> str:
    if rec is None:
        return "no data"
    return f"**{rec.price:,.2f}**\n<t:{rec.ts}:R>"


def make_combined_current(
    fuel: PriceRecord | None, co2: PriceRecord | None
) -> discord.Embed:
    """Combined current-price embed for ``/fuel current`` / ``/co2 current``."""
    e = discord.Embed(title="AM4 prices — current", color=discord.Color.green())
    e.add_field(name="Fuel", value=_commodity_field(fuel), inline=True)
    e.add_field(name="CO₂ Quota", value=_commodity_field(co2), inline=True)
    src = (fuel or co2).source if (fuel or co2) else None
    if src:
        e.set_footer(text=f"source: {src}")
    return e


def _top_n_field(records: list[PriceRecord]) -> str:
    """Render top-N forecast list with HH:MM (user-local) timestamps."""
    if not records:
        return "no data"
    width = max(len(f"{r.price:,.2f}") for r in records)
    # <t:UNIX:t> renders as short time-of-day in the viewer's tz, e.g. "9:30 PM"
    lines = [f"`{r.price:>{width},.2f}`  ·  <t:{r.ts}:t>" for r in records]
    return "\n".join(lines)


def make_combined_best_forecast(
    fuel_top: list[PriceRecord],
    co2_top: list[PriceRecord],
    top_n: int = 5,
) -> discord.Embed:
    """Top N cheapest upcoming forecast slots for fuel and CO2."""
    e = discord.Embed(
        title=f"AM4 prices — {top_n} cheapest upcoming",
        color=discord.Color.gold(),
    )
    if not fuel_top and not co2_top:
        e.description = (
            "No forecast data available. Forecasts require "
            "`PRICE_SOURCE=mgtools` or `PRICE_SOURCE=mock`."
        )
        return e
    e.add_field(name="Fuel", value=_top_n_field(fuel_top), inline=True)
    e.add_field(name="CO₂ Quota", value=_top_n_field(co2_top), inline=True)
    return e


def _resolve_tz(name: str) -> "zoneinfo.ZoneInfo | timezone":
    try:
        return zoneinfo.ZoneInfo(name)
    except zoneinfo.ZoneInfoNotFoundError:
        return timezone.utc


def _terciles(values: list[float]) -> tuple[float, float]:
    """Return (cheap_max, expensive_min) thresholds at the 33rd/66th
    percentiles of ``values``. Used to colour-code the timeline rows.
    Returns (0, 0) for an empty input (no colouring will fire)."""
    if not values:
        return (0.0, 0.0)
    sorted_v = sorted(values)
    n = len(sorted_v)
    cheap = sorted_v[max(0, n // 3 - 1)]
    expensive = sorted_v[min(n - 1, (2 * n) // 3)]
    return (cheap, expensive)


def _coloured(value: float, thresholds: tuple[float, float], width: int) -> str:
    """Format ``value`` to the given column width, ANSI-coloured by tercile."""
    cheap_max, expensive_min = thresholds
    text = f"{int(round(value)):>{width}}"
    if cheap_max < expensive_min:  # otherwise all values are equal
        if value <= cheap_max:
            return f"{_ANSI_GREEN}{text}{_ANSI_RESET}"
        if value >= expensive_min:
            return f"{_ANSI_RED}{text}{_ANSI_RESET}"
    return text


def make_combined_forecast_timeline(
    fuel: list[PriceRecord],
    co2: list[PriceRecord],
    window: Window,
    display_timezone: str = "UTC",
) -> discord.Embed:
    """Chronological forecast timeline for ``/fuel interval`` / ``/co2 interval``.

    Renders one row per upcoming half-hour slot inside the chosen
    window: ``HH:MM   FUEL   CO2``, colour-coded by tercile (green =
    cheap, red = expensive). Day boundaries get a separator label so
    a 24h forecast at 18:00 reads "today's evening then tomorrow's
    morning" naturally.

    Times are formatted in ``display_timezone`` because Discord's
    auto-localising ``<t:UNIX:t>`` syntax doesn't render inside a
    code block — code blocks are literal text. Picking one timezone
    server-side is the cleanest trade-off.
    """
    e = discord.Embed(
        title=f"AM4 prices — next {window.label} forecast",
        color=discord.Color.blurple(),
    )

    if not fuel and not co2:
        e.description = (
            "No forecast data available for this window. Forecasts "
            "require `PRICE_SOURCE=mgtools` or `PRICE_SOURCE=mock`."
        )
        return e

    # Group by timestamp: ts -> [fuel_price | None, co2_price | None]
    by_ts: dict[int, list[float | None]] = {}
    for r in fuel:
        by_ts.setdefault(r.ts, [None, None])[0] = r.price
    for r in co2:
        by_ts.setdefault(r.ts, [None, None])[1] = r.price
    sorted_ts = sorted(by_ts.keys())

    fuel_prices = [v[0] for v in by_ts.values() if v[0] is not None]
    co2_prices = [v[1] for v in by_ts.values() if v[1] is not None]

    fuel_thresh = _terciles(fuel_prices)
    co2_thresh = _terciles(co2_prices)

    # Column widths sized to the largest values we'll display
    fuel_w = max((len(str(int(round(p)))) for p in fuel_prices), default=4)
    co2_w = max((len(str(int(round(p)))) for p in co2_prices), default=3)

    tz = _resolve_tz(display_timezone)
    header = f"{'Time':<5}  {'Fuel':>{fuel_w}}  {'CO₂':>{co2_w}}"
    separator = f"{'-' * 5}  {'-' * fuel_w}  {'-' * co2_w}"
    lines: list[str] = [header, separator]

    last_date = None
    for ts in sorted_ts:
        dt = datetime.fromtimestamp(ts, tz=tz)
        if last_date is not None and dt.date() != last_date:
            day_label = dt.strftime("%a %b %-d")
            lines.append(f"{_ANSI_GREY}── {day_label} ──{_ANSI_RESET}")
        last_date = dt.date()

        time_str = dt.strftime("%H:%M")
        fuel_p, co2_p = by_ts[ts]
        fuel_cell = _coloured(fuel_p, fuel_thresh, fuel_w) if fuel_p is not None else " " * fuel_w
        co2_cell = _coloured(co2_p, co2_thresh, co2_w) if co2_p is not None else " " * co2_w
        lines.append(f"{time_str}  {fuel_cell}  {co2_cell}")

    body = "\n".join(lines)
    if len(body) > _MAX_TIMELINE_BODY:
        body = body[:_MAX_TIMELINE_BODY] + "\n... (truncated)"

    e.description = f"```ansi\n{body}\n```"
    e.set_footer(
        text=(
            f"{len(sorted_ts)} forecasted slots · times in {display_timezone}"
            " · green = cheap · red = expensive"
        )
    )
    return e


def make_status(
    fuel: PriceRecord | None, co2: PriceRecord | None
) -> discord.Embed:
    """Embed for ``/status`` — combined latest fuel + CO2 snapshot."""
    e = discord.Embed(title="AM4 prices — status", color=discord.Color.blue())
    for commodity, rec in (("fuel", fuel), ("co2", co2)):
        if rec is None:
            e.add_field(name=_TITLE[commodity], value="no data", inline=False)
        else:
            e.add_field(
                name=_TITLE[commodity],
                value=f"{rec.price:,.2f}  ·  <t:{rec.ts}:R>  ·  `{rec.source}`",
                inline=False,
            )
    e.set_footer(text=f"am4bot v{__version__}")
    return e
