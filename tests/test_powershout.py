import asyncio
from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import pytest
import pytest_socket

from custom_components.genesisenergy.api import GenesisEnergyApi
from custom_components.genesisenergy.exceptions import (
    ApiError,
    PowerShoutValidationError,
)
from custom_components.genesisenergy.powershout import (
    NZ_TIME_ZONE,
    PowerShoutRedemption,
)


@pytest.fixture
def event_loop(monkeypatch: pytest.MonkeyPatch):
    """Create Windows event loops without exposing sockets to test code."""
    policy = asyncio.get_event_loop_policy()
    original_new_event_loop = policy.new_event_loop

    def create_event_loop():
        """Open the internal socket pair and restore the socket guard."""
        pytest_socket.enable_socket()
        try:
            return original_new_event_loop()
        finally:
            pytest_socket.disable_socket(allow_unix_socket=True)

    monkeypatch.setattr(policy, "new_event_loop", create_event_loop)
    loop = create_event_loop()
    setattr(loop, "__original_fixture_loop", True)
    yield loop
    loop.close()


def _metadata(enabled: bool = True) -> dict:
    """Build release-toggle metadata."""
    return {
        "value": {
            "toggles": {
                "release": [
                    {
                        "id": "powerShoutRedeemPastHours",
                        "enabled": enabled,
                    }
                ]
            }
        }
    }


def _eligible_accounts() -> dict:
    """Build one eligible electricity property."""
    return {
        "loyaltyAccountId": "loyalty-account",
        "eligibleBillingAccounts": [
            {
                "id": "billing-account",
                "billingAccountSites": [
                    {
                        "id": "site-supply-agreement",
                        "address": "1 Test Street",
                        "supplyPoints": [
                            {
                                "id": "0000000001TEST",
                                "supplyAgreementId": "supply-agreement",
                            }
                        ],
                    }
                ]
            }
        ],
    }


class FakeGenesisApi(GenesisEnergyApi):
    """Capture Power Shout calls using contract-shaped responses."""

    def __init__(self, recommendations: list[dict]) -> None:
        self.recommendations = recommendations
        self.setup_calls = 0
        self.recommendation_calls = 0
        self.recommendation_requests: list[dict] = []
        self.date_lookups: list[tuple[str, str]] = []
        self.bookings: list[dict] = []
        self.fail_starts: set[str] = set()

    async def get_initialize_metadata(self) -> dict:
        """Return the enabled release toggle."""
        return _metadata()

    async def get_powershout_info(self) -> dict:
        """Return eligible property identifiers."""
        return _eligible_accounts()

    async def get_powershout_setup(self) -> dict:
        """Return the server redemption window."""
        self.setup_calls += 1
        return {"noOfPastDaysToRedeem": 31}

    async def get_powershout_recommended_hours(self, **kwargs) -> dict:
        """Return ranked hours and private recommendation vouchers."""
        self.recommendation_calls += 1
        self.recommendation_requests.append(kwargs)
        return {
            "recommendedHours": self.recommendations,
            "availableBalance": {
                "hours": 4,
                "vouchers": [
                    {"number": "recommended-1"},
                    {"number": "recommended-2"},
                    {"number": "recommended-3"},
                    {"number": "recommended-4"},
                ],
            },
        }

    async def get_powershout_vouchers_for_date(
        self, selected_date: str, supply_point_id: str
    ) -> dict:
        """Return date-specific vouchers and irrelevant existing bookings."""
        self.date_lookups.append((selected_date, supply_point_id))
        return {
            "vouchers": ["date-1", "date-2", "date-3", "date-4"],
            "bookings": [{"id": "must-not-offset-vouchers"}],
        }

    async def get_generation_mix(self) -> list[dict]:
        """Return an eco-hour forecast for tomorrow."""
        tomorrow = datetime.now(NZ_TIME_ZONE).date() + timedelta(days=1)
        return [
            {
                "Day": tomorrow.isoformat(),
                "HourlyBreakdown": [
                    {"EcoFriendly": hour % 2 == 0} for hour in range(24)
                ],
            }
        ]

    async def add_powershout_booking(self, **payload) -> dict:
        """Capture a booking or raise a configured API failure."""
        if payload["start_date_str"] in self.fail_starts:
            raise ApiError(
                "Duplicate",
                status=400,
                error_type="/error/add_booking/duplicate_booking",
            )
        self.bookings.append(payload)
        return {"status": 200}


class PowerShoutRedemptionTests(IsolatedAsyncioTestCase):
    """Verify the first-party Power Shout booking policies."""

    def setUp(self) -> None:
        """Create two eligible ranked hours."""
        past_date = datetime.now(NZ_TIME_ZONE).date() - timedelta(days=3)
        self.starts = [
            f"{past_date.isoformat()}T18:00:00",
            f"{past_date.isoformat()}T20:00:00",
        ]
        recommendations = [
            {"dateTime": start, "day": "Wednesday", "time": "6:00pm"}
            for start in self.starts
        ]
        recommendations[1]["time"] = "8:00pm"
        self.api = FakeGenesisApi(recommendations)
        self.redemption = PowerShoutRedemption(self.api)

    async def _load_state(self):
        """Load and return the only property state."""
        states = await self.redemption.async_load_states(
            _metadata(),
            _eligible_accounts(),
        )
        return next(iter(states.values()))

    async def test_feature_toggle_blocks_retrospective_calls(self) -> None:
        """Keep setup and recommendations behind the release toggle."""
        states = await self.redemption.async_load_states(
            _metadata(enabled=False),
            _eligible_accounts(),
        )

        state = next(iter(states.values()))
        self.assertFalse(state.feature_enabled)
        self.assertEqual(self.api.setup_calls, 0)
        self.assertEqual(self.api.recommendation_calls, 0)

    async def test_missing_feature_toggle_uses_setup_capability(self) -> None:
        """Use the setup endpoint when rollout metadata omits the toggle."""
        states = await self.redemption.async_load_states(
            {"value": {"toggles": {"release": []}}},
            _eligible_accounts(),
        )

        state = next(iter(states.values()))
        self.assertTrue(state.feature_enabled)
        self.assertEqual(state.past_days, 31)
        self.assertEqual(self.api.setup_calls, 1)
        self.assertEqual(self.api.recommendation_calls, 1)

    async def test_parent_billing_account_id_loads_recommendations(self) -> None:
        """Use the enclosing billing account ID when the site omits it."""
        state = await self._load_state()

        self.assertEqual(state.site.billing_account_id, "billing-account")
        self.assertEqual(
            self.api.recommendation_requests[0]["billing_account_id"],
            "billing-account",
        )

    async def test_recommended_hours_use_one_private_voucher_each(self) -> None:
        """Book selected recommendations separately in selection order."""
        state = await self._load_state()
        keys = [item.key for item in reversed(state.recommendations)]

        result = await self.redemption.async_redeem_past(
            state.site.key,
            recommendation_keys=keys,
        )

        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(
            [item["recommendation_key"] for item in result["succeeded"]],
            keys,
        )
        self.assertEqual([item["duration"] for item in self.api.bookings], [1, 1])
        self.assertEqual(
            [item["vouchers"] for item in self.api.bookings],
            [["recommended-1"], ["recommended-2"]],
        )
        self.assertEqual(
            [item["eco_hours"] for item in self.api.bookings],
            [[], []],
        )

    async def test_recommendations_and_manual_start_are_mutually_exclusive(self) -> None:
        """Reject ambiguous action input before spending a voucher."""
        state = await self._load_state()

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_redeem_past(
                state.site.key,
                recommendation_keys=[state.recommendations[0].key],
                manual_start=self.starts[0],
            )

        self.assertEqual(self.api.bookings, [])

    async def test_recommended_batch_returns_partial_results(self) -> None:
        """Keep one failed recommendation separate from successful hours."""
        state = await self._load_state()
        self.api.fail_starts.add(self.starts[1])

        result = await self.redemption.async_redeem_past(
            state.site.key,
            recommendation_keys=[item.key for item in state.recommendations],
        )

        self.assertEqual(len(result["succeeded"]), 1)
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(result["failed"][0]["code"], "duplicate_booking")
        self.assertEqual(
            result["failed"][0]["recommendation_key"],
            state.recommendations[1].key,
        )

    async def test_manual_past_booking_uses_date_vouchers(self) -> None:
        """Use date-specific vouchers for one explicit manual window."""
        state = await self._load_state()
        manual_start = (
            datetime.now(NZ_TIME_ZONE).date() - timedelta(days=2)
        ).isoformat() + "T10:00:00"

        result = await self.redemption.async_redeem_past(
            state.site.key,
            manual_start=manual_start,
            duration=2,
        )

        self.assertEqual(len(result["succeeded"]), 1)
        self.assertEqual(self.api.bookings[0]["duration"], 2)
        self.assertEqual(
            self.api.bookings[0]["vouchers"],
            ["date-1", "date-2"],
        )
        self.assertEqual(self.api.bookings[0]["eco_hours"], [])

    async def test_future_booking_is_one_full_duration_request(self) -> None:
        """Use the local date and first N vouchers in one future request."""
        await self._load_state()
        tomorrow = datetime.now(NZ_TIME_ZONE).date() + timedelta(days=1)
        start = datetime.combine(tomorrow, datetime.min.time()).replace(hour=18)

        result = await self.redemption.async_book_future(start, 2)

        self.assertEqual(result["duration_hours"], 2)
        self.assertEqual(len(self.api.bookings), 1)
        self.assertEqual(self.api.bookings[0]["duration"], 2)
        self.assertEqual(
            self.api.bookings[0]["vouchers"],
            ["date-1", "date-2"],
        )
        self.assertEqual(
            self.api.date_lookups[0][0],
            f"{tomorrow.isoformat()}T00:00:00.000Z",
        )
