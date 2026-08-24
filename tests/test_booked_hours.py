from unittest import TestCase

from custom_components.genesisenergy.coordinator import (
    GenesisEnergyDataUpdateCoordinator,
)

# The expansion reads nothing off the coordinator, so it is exercised unbound
# rather than standing up Home Assistant.
_booked_hour_starts = GenesisEnergyDataUpdateCoordinator._booked_hour_starts


class BookedHourTests(TestCase):
    """Verify which local hours a Genesis booking covers."""

    def test_a_one_hour_booking_covers_its_own_hour(self) -> None:
        """Cover exactly the booked hour."""
        data = {
            "bookings": [
                {"startDateTime": "2026-08-24T20:00:00.000+12:00", "duration": 1}
            ]
        }

        self.assertEqual(
            _booked_hour_starts(None, data), frozenset({"2026-08-24T20:00:00"})
        )

    def test_a_longer_booking_covers_every_hour_it_runs(self) -> None:
        """Cover each hour of a multi-hour booking."""
        data = {
            "bookings": [
                {"startDateTime": "2026-08-24T20:00:00.000+12:00", "duration": 3}
            ]
        }

        self.assertEqual(
            _booked_hour_starts(None, data),
            frozenset(
                {
                    "2026-08-24T20:00:00",
                    "2026-08-24T21:00:00",
                    "2026-08-24T22:00:00",
                }
            ),
        )

    def test_a_missing_duration_covers_one_hour(self) -> None:
        """Assume one hour when Genesis omits the duration."""
        data = {"bookings": [{"startDateTime": "2026-08-24T20:00:00.000+12:00"}]}

        self.assertEqual(
            _booked_hour_starts(None, data), frozenset({"2026-08-24T20:00:00"})
        )

    def test_bookings_are_read_in_new_zealand_time(self) -> None:
        """Convert an offset timestamp to the local hour used for ranking."""
        data = {
            "bookings": [
                {"startDateTime": "2026-08-24T08:00:00.000+00:00", "duration": 1}
            ]
        }

        self.assertEqual(
            _booked_hour_starts(None, data), frozenset({"2026-08-24T20:00:00"})
        )

    def test_unusable_bookings_are_ignored(self) -> None:
        """Skip bookings without a usable start."""
        data = {
            "bookings": [
                {"duration": 1},
                {"startDateTime": "not-a-date", "duration": 1},
                "nonsense",
                {"startDateTime": "2026-08-24T20:00:00.000+12:00", "duration": 1},
            ]
        }

        self.assertEqual(
            _booked_hour_starts(None, data), frozenset({"2026-08-24T20:00:00"})
        )

    def test_a_shapeless_payload_covers_nothing(self) -> None:
        """Return no hours when Genesis sends no booking list."""
        self.assertEqual(_booked_hour_starts(None, None), frozenset())
        self.assertEqual(_booked_hour_starts(None, {"bookings": "nope"}), frozenset())
