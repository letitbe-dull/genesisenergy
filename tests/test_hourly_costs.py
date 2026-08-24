from datetime import date, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase

from custom_components.genesisenergy import hourly_costs
from custom_components.genesisenergy.exceptions import ApiError
from custom_components.genesisenergy.hourly_costs import (
    HourlyCostSource,
    _missing_dates,
    _parse_usage,
)
from custom_components.genesisenergy.powershout import HourCost

WINDOW_START = date(2026, 7, 24)
WINDOW_END = date(2026, 8, 23)


def _recorded(days: list[date], hours_per_day: int = 24) -> dict[str, HourCost]:
    """Build recorded hours for whole days."""
    recorded: dict[str, HourCost] = {}
    for day in days:
        for hour in range(hours_per_day):
            key = f"{day.isoformat()}T{hour:02d}:00:00"
            recorded[key] = HourCost(key, 1.0, 0.10)
    return recorded


def _all_days(earliest: date, latest: date) -> list[date]:
    """List every date in an inclusive window."""
    return [
        earliest + timedelta(days=offset)
        for offset in range((latest - earliest).days + 1)
    ]


class MissingDateTests(TestCase):
    """Verify which eligible dates count as absent from the recorder."""

    def test_a_fully_covered_window_needs_no_fetch(self) -> None:
        """Report nothing missing when every day is recorded."""
        recorded = _recorded(_all_days(WINDOW_START, WINDOW_END))

        self.assertEqual(_missing_dates(recorded, WINDOW_START, WINDOW_END), [])

    def test_only_absent_days_are_reported(self) -> None:
        """Report the trailing days Genesis has not delivered yet."""
        days = _all_days(WINDOW_START, WINDOW_END - timedelta(days=3))
        recorded = _recorded(days)

        missing = _missing_dates(recorded, WINDOW_START, WINDOW_END)

        self.assertEqual(
            missing,
            [date(2026, 8, 21), date(2026, 8, 22), date(2026, 8, 23)],
        )

    def test_small_holes_do_not_count_as_missing(self) -> None:
        """Tolerate the gaps Genesis leaves in an otherwise complete day."""
        recorded = _recorded(_all_days(WINDOW_START, WINDOW_END), hours_per_day=21)

        self.assertEqual(_missing_dates(recorded, WINDOW_START, WINDOW_END), [])

    def test_a_mostly_empty_day_counts_as_missing(self) -> None:
        """Treat a day with only a few hours as absent."""
        recorded = _recorded([WINDOW_START], hours_per_day=4)

        missing = _missing_dates(recorded, WINDOW_START, WINDOW_START)

        self.assertEqual(missing, [WINDOW_START])

    def test_an_empty_recorder_reports_the_whole_window(self) -> None:
        """Report every eligible day when nothing is recorded."""
        missing = _missing_dates({}, WINDOW_START, WINDOW_END)

        self.assertEqual(len(missing), 31)


class ParseUsageTests(TestCase):
    """Verify how Genesis hourly usage becomes local hour costs."""

    def test_hourly_usage_becomes_local_hours(self) -> None:
        """Key each record by its local hour with kWh and cost."""
        response = {
            "usage": [
                {
                    "startDate": "2026-08-05T08:00:00+12:00",
                    "kw": 4.12,
                    "costNZD": 1.43,
                }
            ]
        }

        hours = _parse_usage(response)

        self.assertEqual(list(hours), ["2026-08-05T08:00:00"])
        self.assertEqual(hours["2026-08-05T08:00:00"].cost, 1.43)
        self.assertEqual(hours["2026-08-05T08:00:00"].kwh, 4.12)

    def test_unusable_records_are_skipped(self) -> None:
        """Ignore records without a usable start or number."""
        response = {
            "usage": [
                {"kw": 1.0, "costNZD": 1.0},
                {"startDate": "not-a-date", "kw": 1.0, "costNZD": 1.0},
                {"startDate": "2026-08-05T08:00:00+12:00", "costNZD": "abc"},
                {"startDate": "2026-08-06T08:00:00+12:00", "kw": 1.0, "costNZD": 0.5},
            ]
        }

        hours = _parse_usage(response)

        self.assertEqual(list(hours), ["2026-08-06T08:00:00"])

    def test_a_shapeless_response_yields_nothing(self) -> None:
        """Return no hours for a response without a usage list."""
        self.assertEqual(_parse_usage({"usage": "nope"}), {})
        self.assertEqual(_parse_usage(None), {})


class FakeUsageApi:
    """Serve hourly usage for requested date ranges."""

    def __init__(self, error: Exception | None = None) -> None:
        self.ranges: list[tuple[str, str]] = []
        self.error = error

    async def get_energy_data_for_period(self, start: str, end: str) -> dict:
        """Record the requested range and return one hour per day in it."""
        self.ranges.append((start, end))
        if self.error is not None:
            raise self.error
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
        return {
            "usage": [
                {
                    "startDate": f"{day.isoformat()}T08:00:00+12:00",
                    "kw": 2.0,
                    "costNZD": 0.75,
                }
                for day in _all_days(first, last)
            ]
        }


class FallbackFetchTests(IsolatedAsyncioTestCase):
    """Verify the API fallback used when the recorder is short of data."""

    def setUp(self) -> None:
        """Remove the inter-chunk pause so tests do not wait."""
        self._pause = hourly_costs.CHUNK_PAUSE
        hourly_costs.CHUNK_PAUSE = 0

    def tearDown(self) -> None:
        """Restore the inter-chunk pause."""
        hourly_costs.CHUNK_PAUSE = self._pause

    async def test_long_windows_are_split_into_short_requests(self) -> None:
        """Never ask Genesis for more days than it will answer for."""
        api = FakeUsageApi()
        source = HourlyCostSource(None, api)

        await source._async_from_api(_all_days(WINDOW_START, WINDOW_END))

        self.assertEqual(len(api.ranges), 8)
        for start, end in api.ranges:
            span = (date.fromisoformat(end) - date.fromisoformat(start)).days
            self.assertLess(span, hourly_costs.CHUNK_DAYS)

    async def test_only_missing_days_are_requested(self) -> None:
        """Fetch the absent days rather than the whole window."""
        api = FakeUsageApi()
        source = HourlyCostSource(None, api)

        await source._async_from_api([date(2026, 8, 22), date(2026, 8, 23)])

        self.assertEqual(api.ranges, [("2026-08-22", "2026-08-23")])

    async def test_a_repeat_request_is_served_from_cache(self) -> None:
        """Ask Genesis once for the same set of missing days."""
        api = FakeUsageApi()
        source = HourlyCostSource(None, api)
        missing = [date(2026, 8, 22), date(2026, 8, 23)]

        await source._async_from_api(missing)
        await source._async_from_api(missing)

        self.assertEqual(len(api.ranges), 1)

    async def test_a_failed_chunk_does_not_lose_the_rest(self) -> None:
        """Return nothing rather than raising when Genesis refuses a range."""
        api = FakeUsageApi(error=ApiError("boom", status=500))
        source = HourlyCostSource(None, api)

        hours = await source._async_from_api([date(2026, 8, 22)])

        self.assertEqual(hours, {})

    async def test_recorded_hours_win_over_fetched_hours(self) -> None:
        """Prefer the recorder, which is what the rest of Home Assistant reports."""
        api = FakeUsageApi()
        source = HourlyCostSource(None, api)
        recorded = _recorded([date(2026, 8, 22)])

        async def _fake_statistics(earliest: date, latest: date) -> dict:
            """Return the recorded hours regardless of the window."""
            return recorded

        source._async_from_statistics = _fake_statistics

        hours = await source.async_hour_costs(date(2026, 8, 22), date(2026, 8, 23))

        self.assertEqual(hours["2026-08-22T08:00:00"].cost, 0.10)
        self.assertEqual(hours["2026-08-23T08:00:00"].cost, 0.75)
