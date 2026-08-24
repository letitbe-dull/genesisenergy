"""Per-hour electricity cost lookup for retrospective Power Shout ranking.

Costs come from the hourly long-term statistics this integration already writes
(``genesisenergy:electricity_cost_daily`` and ``..._consumption_daily``, both
recorded per hour from the Genesis ``kw``/``costNZD`` fields). The Genesis API is
only called when the recorder does not yet cover the eligible window, which
happens on a fresh install or after a gap in polling.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import GenesisEnergyApi
from .const import (
    LOGGER,
    STATISTIC_ID_ELECTRICITY_CONSUMPTION,
    STATISTIC_ID_ELECTRICITY_COST,
)
from .exceptions import GenesisEnergyError
from .powershout import NZ_TIME_ZONE, HourCost

# Genesis meter data arrives late and with occasional holes, so a date only
# counts as missing when most of its hours are absent.
MIN_HOURS_PER_DAY = 20

# Genesis answers HTTP 500 for long ranges, so fetch the same span the backfill
# service uses, with the same pause between requests.
CHUNK_DAYS = 4
CHUNK_PAUSE = 1

# How long to wait before retrying after a failed backfill.
BACKFILL_RETRY = timedelta(hours=6)


def _local_hour_key(value: datetime) -> str:
    """Return the naive local hour a statistics row belongs to."""
    return (
        value.astimezone(NZ_TIME_ZONE)
        .replace(minute=0, second=0, microsecond=0, tzinfo=None)
        .strftime("%Y-%m-%dT%H:%M:%S")
    )


def _expected_hours(earliest: date, latest: date) -> int:
    """Return how many hours a fully covered window would hold."""
    return max(0, (latest - earliest).days + 1) * 24


def _row_value(row: Mapping[str, Any]) -> float | None:
    """Return the per-hour value from a statistics row."""
    value = row.get("state")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_start(row: Mapping[str, Any]) -> datetime | None:
    """Return the UTC start of a statistics row."""
    start = row.get("start")
    if isinstance(start, datetime):
        return start
    if isinstance(start, (int, float)):
        return dt_util.utc_from_timestamp(start)
    return None


class HourlyCostSource:
    """Serve per-hour costs for the retrospective eligibility window."""

    def __init__(self, hass: HomeAssistant, api: GenesisEnergyApi) -> None:
        self._hass = hass
        self._api = api
        self._lock = asyncio.Lock()
        self._api_hours: dict[str, HourCost] = {}
        self._api_window: frozenset[date] | None = None
        self._last_attempt: datetime | None = None

    async def async_hour_costs(
        self, earliest: date, latest: date
    ) -> dict[str, HourCost]:
        """Return recorded hours across the window, keyed by local hour."""
        if latest < earliest:
            return {}
        hours = await self._async_from_statistics(earliest, latest)
        missing = _missing_dates(hours, earliest, latest)
        if not missing:
            return hours

        LOGGER.debug(
            "Power Shout: %s of %s eligible days missing from statistics",
            len(missing),
            (latest - earliest).days + 1,
        )
        fallback = await self._async_from_api(missing)
        # Recorded hours win: they are what the rest of Home Assistant reports.
        return {**fallback, **hours}

    async def _async_from_statistics(
        self, earliest: date, latest: date
    ) -> dict[str, HourCost]:
        """Read the window out of long-term statistics."""
        start = datetime.combine(earliest, datetime.min.time(), NZ_TIME_ZONE)
        end = datetime.combine(
            latest + timedelta(days=1), datetime.min.time(), NZ_TIME_ZONE
        )
        try:
            stats = await get_instance(self._hass).async_add_executor_job(
                statistics_during_period,
                self._hass,
                start,
                end,
                {STATISTIC_ID_ELECTRICITY_COST, STATISTIC_ID_ELECTRICITY_CONSUMPTION},
                "hour",
                None,
                {"state"},
            )
        except Exception:  # noqa: BLE001 - recorder failures must not break a refresh
            LOGGER.warning("Power Shout: could not read hourly statistics", exc_info=True)
            return {}

        kwh_by_hour: dict[str, float] = {}
        for row in stats.get(STATISTIC_ID_ELECTRICITY_CONSUMPTION, []):
            row_start = _row_start(row)
            value = _row_value(row)
            if row_start is not None and value is not None:
                kwh_by_hour[_local_hour_key(row_start)] = value

        hours: dict[str, HourCost] = {}
        for row in stats.get(STATISTIC_ID_ELECTRICITY_COST, []):
            row_start = _row_start(row)
            value = _row_value(row)
            if row_start is None or value is None:
                continue
            key = _local_hour_key(row_start)
            hours[key] = HourCost(start=key, kwh=kwh_by_hour.get(key, 0.0), cost=value)
        return hours

    async def _async_from_api(self, missing: list[date]) -> dict[str, HourCost]:
        """Fetch the missing dates from Genesis, in chunks, and cache them."""
        async with self._lock:
            wanted = frozenset(missing)
            if self._api_window == wanted and self._api_hours:
                return self._api_hours
            now = dt_util.utcnow()
            if self._last_attempt and now - self._last_attempt < BACKFILL_RETRY:
                # Cached hours stay keyed by time, so serving them past the
                # window's daily roll is harmless — callers filter by date.
                return self._api_hours
            self._last_attempt = now

            hours: dict[str, HourCost] = {}
            chunks = [
                missing[index : index + CHUNK_DAYS]
                for index in range(0, len(missing), CHUNK_DAYS)
            ]
            for position, chunk in enumerate(chunks):
                if position:
                    await asyncio.sleep(CHUNK_PAUSE)
                try:
                    response = await self._api.get_energy_data_for_period(
                        chunk[0].isoformat(), chunk[-1].isoformat()
                    )
                except GenesisEnergyError as err:
                    LOGGER.debug(
                        "Power Shout: no hourly usage for %s to %s (%s)",
                        chunk[0],
                        chunk[-1],
                        err,
                    )
                    continue
                hours.update(_parse_usage(response))

            if not hours:
                LOGGER.warning(
                    "Power Shout: Genesis returned no hourly usage for the %s "
                    "day(s) missing from statistics; ranking uses what is recorded",
                    len(missing),
                )
            self._api_hours = hours
            self._api_window = wanted
            return hours


def _missing_dates(
    hours: Mapping[str, HourCost], earliest: date, latest: date
) -> list[date]:
    """Return eligible dates the recorder does not meaningfully cover."""
    counts: dict[str, int] = {}
    for key in hours:
        counts[key[:10]] = counts.get(key[:10], 0) + 1

    missing: list[date] = []
    current = earliest
    while current <= latest:
        if counts.get(current.isoformat(), 0) < MIN_HOURS_PER_DAY:
            missing.append(current)
        current += timedelta(days=1)
    return missing


def _parse_usage(response: Any) -> dict[str, HourCost]:
    """Normalize a site-usage response into local hours."""
    if not isinstance(response, Mapping):
        return {}
    entries = response.get("usage")
    if not isinstance(entries, list):
        return {}

    hours: dict[str, HourCost] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        raw_start = entry.get("startDate")
        if not raw_start:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_start))
        except (TypeError, ValueError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=NZ_TIME_ZONE)
        try:
            cost = float(entry.get("costNZD") or 0.0)
            kwh = float(entry.get("kw") or 0.0)
        except (TypeError, ValueError):
            continue
        key = _local_hour_key(parsed)
        hours[key] = HourCost(start=key, kwh=kwh, cost=cost)
    return hours
