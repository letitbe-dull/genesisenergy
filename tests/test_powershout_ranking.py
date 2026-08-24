from unittest import TestCase

from custom_components.genesisenergy.powershout import (
    HourCost,
    PowerShoutRecommendation,
    build_ranked_hours,
)


def _hours(**costs: float) -> dict[str, HourCost]:
    """Build hour costs keyed by local hour, priced at cost with 2x the kWh."""
    return {
        start.replace("_", ":"): HourCost(start.replace("_", ":"), cost * 2, cost)
        for start, cost in costs.items()
    }


def _recommendation(start: str, key: str = "rec") -> PowerShoutRecommendation:
    """Build one Genesis recommendation for a local hour."""
    return PowerShoutRecommendation(
        key=key, date_time=start, day="Wed 05 Aug", time="8am - 9am"
    )


class BuildRankedHoursTests(TestCase):
    """Verify how eligible past hours are ranked and filtered."""

    def setUp(self) -> None:
        """Price four eligible hours."""
        self.hours = _hours(
            **{
                "2026-08-05T08_00_00": 1.43,
                "2026-08-17T10_00_00": 1.35,
                "2026-07-30T08_00_00": 1.29,
                "2026-07-28T08_00_00": 1.27,
            }
        )

    def test_orders_by_credit_not_by_genesis(self) -> None:
        """Rank by what each hour gives back, ignoring Genesis' own order."""
        recommendations = (_recommendation("2026-07-28T08:00:00"),)

        ranked = build_ranked_hours(self.hours, recommendations, frozenset(), 10)

        self.assertEqual(
            [item.start for item in ranked],
            [
                "2026-08-05T08:00:00",
                "2026-08-17T10:00:00",
                "2026-07-30T08:00:00",
                "2026-07-28T08:00:00",
            ],
        )

    def test_excluded_hours_are_removed_not_demoted(self) -> None:
        """Drop hours already covered by a booking or a past redemption."""
        excluded = frozenset(
            {"2026-08-05T08:00:00", "2026-07-30T08:00:00"}
        )

        ranked = build_ranked_hours(self.hours, (), excluded, 10)

        starts = [item.start for item in ranked]
        self.assertEqual(starts, ["2026-08-17T10:00:00", "2026-07-28T08:00:00"])

    def test_hours_worth_nothing_are_skipped(self) -> None:
        """Ignore hours that would return no credit."""
        hours = _hours(**{"2026-08-05T08_00_00": 0.0, "2026-08-06T08_00_00": 0.5})

        ranked = build_ranked_hours(hours, (), frozenset(), 10)

        self.assertEqual([item.start for item in ranked], ["2026-08-06T08:00:00"])

    def test_limit_keeps_the_most_valuable_hours(self) -> None:
        """Publish only the top hours when a limit applies."""
        ranked = build_ranked_hours(self.hours, (), frozenset(), 2)

        self.assertEqual(
            [item.start for item in ranked],
            ["2026-08-05T08:00:00", "2026-08-17T10:00:00"],
        )

    def test_genesis_picks_keep_their_key_and_position(self) -> None:
        """Carry Genesis' recommendation key and rank onto matching hours."""
        recommendations = (
            _recommendation("2026-08-17T10:00:00", key="first"),
            _recommendation("2026-07-28T08:00:00", key="second"),
        )

        ranked = build_ranked_hours(self.hours, recommendations, frozenset(), 10)
        by_start = {item.start: item for item in ranked}

        self.assertEqual(by_start["2026-08-17T10:00:00"].recommendation_key, "first")
        self.assertEqual(by_start["2026-08-17T10:00:00"].genesis_rank, 1)
        self.assertEqual(by_start["2026-07-28T08:00:00"].genesis_rank, 2)
        self.assertIsNone(by_start["2026-08-05T08:00:00"].recommendation_key)
        self.assertIsNone(by_start["2026-08-05T08:00:00"].genesis_rank)

    def test_equal_credit_falls_back_to_time_order(self) -> None:
        """Keep ranking stable when two hours return the same credit."""
        hours = _hours(
            **{"2026-08-06T08_00_00": 1.10, "2026-08-05T08_00_00": 1.10}
        )

        ranked = build_ranked_hours(hours, (), frozenset(), 10)

        self.assertEqual(
            [item.start for item in ranked],
            ["2026-08-05T08:00:00", "2026-08-06T08:00:00"],
        )

    def test_labels_read_as_local_time(self) -> None:
        """Label each hour with its day and a 12-hour start time."""
        hours = _hours(
            **{
                "2026-08-05T00_00_00": 1.50,
                "2026-08-05T12_00_00": 1.40,
                "2026-08-05T13_00_00": 1.30,
            }
        )

        ranked = build_ranked_hours(hours, (), frozenset(), 10)

        self.assertEqual(
            [item.time for item in ranked], ["12am", "12pm", "1pm"]
        )
        self.assertEqual(ranked[0].day, "Wed 05 Aug")

    def test_published_fields_are_display_ready(self) -> None:
        """Round the published credit and usage for the card."""
        hours = {
            "2026-08-05T08:00:00": HourCost("2026-08-05T08:00:00", 4.1234, 1.4321)
        }

        published = build_ranked_hours(hours, (), frozenset(), 10)[0].as_dict()

        self.assertEqual(published["kwh"], 4.12)
        self.assertEqual(published["cost"], 1.43)
        self.assertNotIn("booked", published)
