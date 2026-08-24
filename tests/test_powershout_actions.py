from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase

from custom_components.genesisenergy.api import GenesisEnergyApi
from custom_components.genesisenergy.exceptions import (
    ApiError,
    PowerShoutUnavailableError,
    PowerShoutValidationError,
)
from custom_components.genesisenergy.powershout import (
    NZ_TIME_ZONE,
    PowerShoutRedemption,
)

LOYALTY_ACCOUNT_ID = "GENE-Gentrack-920521052"
BILLING_ACCOUNT_ID = "GENE-Gentrack-1003880385"


def _metadata() -> dict:
    """Build metadata with the retrospective release toggle enabled."""
    return {
        "value": {
            "toggles": {
                "release": [
                    {"id": "powerShoutRedeemPastHours", "enabled": True}
                ]
            }
        }
    }


def _eligible_accounts() -> dict:
    """Build one eligible electricity property."""
    return {
        "loyaltyAccountId": LOYALTY_ACCOUNT_ID,
        "eligibleBillingAccounts": [
            {
                "id": BILLING_ACCOUNT_ID,
                "billingAccountSites": [
                    {
                        "id": "site-supply-agreement",
                        "address": "1 Test Street",
                        "supplyPoints": [
                            {
                                "id": "ELECTRICITY-1002179969UN506",
                                "supplyAgreementId": "supply-agreement",
                            }
                        ],
                    }
                ],
            }
        ],
    }


class FakeGenesisApi(GenesisEnergyApi):
    """Capture Power Shout calls using contract-shaped responses."""

    def __init__(self) -> None:
        self.bookings: list[dict] = []
        self.deletes: list[dict] = []
        self.date_lookups: list[str] = []
        self.remote_bookings: list[dict] = []
        self.add_error: ApiError | None = None
        self.delete_error: ApiError | None = None

    async def get_initialize_metadata(self) -> dict:
        """Return the enabled release toggle."""
        return _metadata()

    async def get_powershout_info(self) -> dict:
        """Return eligible property identifiers."""
        return _eligible_accounts()

    async def get_powershout_setup(self) -> dict:
        """Return the server redemption window."""
        return {"noOfPastDaysToRedeem": 31}

    async def get_powershout_recommended_hours(self, **kwargs) -> dict:
        """Return no ranked hours and a usable balance."""
        return {
            "recommendedHours": [],
            "availableBalance": {
                "hours": 6,
                "vouchers": [{"number": f"recommended-{index}"} for index in range(6)],
            },
        }

    async def get_powershout_vouchers_for_date(
        self, selected_date: str, supply_point_id: str
    ) -> dict:
        """Return two vouchers per requested date."""
        self.date_lookups.append(selected_date)
        day = selected_date[:10]
        return {"vouchers": [f"{day}-a", f"{day}-b"]}

    async def get_generation_mix(self) -> list[dict]:
        """Return no eco-hour forecast."""
        return []

    async def get_powershout_bookings(self) -> dict:
        """Return the bookings Genesis currently holds."""
        return {"bookings": self.remote_bookings}

    async def add_powershout_booking(self, **payload) -> dict:
        """Capture a booking, optionally raising a configured API failure."""
        if self.add_error is not None:
            raise self.add_error
        self.bookings.append(payload)
        return {"status": 200}

    async def delete_powershout_booking(self, **payload) -> dict:
        """Capture a cancellation, optionally raising a configured failure."""
        self.deletes.append(payload)
        if self.delete_error is not None:
            raise self.delete_error
        return {"status": 200}


class PowerShoutActionTests(IsolatedAsyncioTestCase):
    """Verify cancellation and multi-hour retrospective redemption."""

    def setUp(self) -> None:
        """Create a redemption manager over a fake Genesis API."""
        self.api = FakeGenesisApi()
        self.redemption = PowerShoutRedemption(self.api)
        today = datetime.now(NZ_TIME_ZONE).date()
        self.first_day = today - timedelta(days=3)
        self.second_day = today - timedelta(days=2)

    async def _site_key(self) -> str:
        """Load property state and return the only site key."""
        states = await self.redemption.async_load_states(
            _metadata(), _eligible_accounts()
        )
        return next(iter(states))

    # ── cancellation ──

    async def test_cancel_sends_the_loyalty_account_id(self) -> None:
        """Send the loyalty account id Genesis expects in billingAccountId."""
        site_key = await self._site_key()

        await self.redemption.async_cancel_booking("booking-1", site_key)

        self.assertEqual(
            self.api.deletes,
            [{"booking_id": "booking-1", "billing_account_id": LOYALTY_ACCOUNT_ID}],
        )

    async def test_cancel_accepts_a_booking_genesis_already_removed(self) -> None:
        """Treat a vanished booking as cancelled despite an error response."""
        site_key = await self._site_key()
        self.api.delete_error = ApiError("boom", status=400)
        self.api.remote_bookings = [{"id": "another-booking"}]

        await self.redemption.async_cancel_booking("booking-1", site_key)

        self.assertEqual(len(self.api.deletes), 1)

    async def test_cancel_fails_when_the_booking_survives(self) -> None:
        """Report failure while Genesis still holds the booking."""
        site_key = await self._site_key()
        self.api.delete_error = ApiError("boom", status=400)
        self.api.remote_bookings = [{"id": "booking-1"}]

        with self.assertRaises(PowerShoutUnavailableError):
            await self.redemption.async_cancel_booking("booking-1", site_key)

    async def test_cancel_requires_a_booking(self) -> None:
        """Reject a cancellation with no booking."""
        site_key = await self._site_key()

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_cancel_booking("", site_key)

    # ── multi-hour retrospective redemption ──

    async def test_hours_on_one_date_share_that_date_lookup(self) -> None:
        """Fetch a date's vouchers once and spend one per selected hour."""
        site_key = await self._site_key()
        starts = [
            f"{self.first_day.isoformat()}T08:00:00",
            f"{self.first_day.isoformat()}T09:00:00",
        ]

        result = await self.redemption.async_redeem_past(site_key, manual_start=starts)

        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(len(result["succeeded"]), 2)
        self.assertEqual(len(self.api.date_lookups), 1)
        self.assertEqual(
            [booking["vouchers"] for booking in self.api.bookings],
            [[f"{self.first_day.isoformat()}-a"], [f"{self.first_day.isoformat()}-b"]],
        )

    async def test_hours_across_dates_use_their_own_vouchers(self) -> None:
        """Look each distinct date up once and never reuse a voucher."""
        site_key = await self._site_key()
        starts = [
            f"{self.first_day.isoformat()}T08:00:00",
            f"{self.second_day.isoformat()}T09:00:00",
        ]

        await self.redemption.async_redeem_past(site_key, manual_start=starts)

        self.assertEqual(len(self.api.date_lookups), 2)
        vouchers = [booking["vouchers"][0] for booking in self.api.bookings]
        self.assertEqual(len(set(vouchers)), 2)

    async def test_selecting_several_hours_forbids_a_longer_duration(self) -> None:
        """Redeem exactly one hour each when several hours are selected."""
        site_key = await self._site_key()
        starts = [
            f"{self.first_day.isoformat()}T08:00:00",
            f"{self.first_day.isoformat()}T10:00:00",
        ]

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_redeem_past(
                site_key, manual_start=starts, duration=2
            )

    async def test_one_hour_may_still_span_several_hours(self) -> None:
        """Allow a multi-hour duration from a single past start."""
        site_key = await self._site_key()
        start = f"{self.first_day.isoformat()}T08:00:00"

        await self.redemption.async_redeem_past(
            site_key, manual_start=start, duration=2
        )

        self.assertEqual(self.api.bookings[0]["duration"], 2)
        self.assertEqual(len(self.api.bookings[0]["vouchers"]), 2)

    async def test_recommendations_and_times_cannot_be_mixed(self) -> None:
        """Reject a request that names both recommendations and times."""
        site_key = await self._site_key()

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_redeem_past(
                site_key,
                recommendation_keys=["some-key"],
                manual_start=[f"{self.first_day.isoformat()}T08:00:00"],
            )

    async def test_the_same_hour_cannot_be_selected_twice(self) -> None:
        """Reject duplicate hours in one redemption."""
        site_key = await self._site_key()
        start = f"{self.first_day.isoformat()}T08:00:00"

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_redeem_past(
                site_key, manual_start=[start, start]
            )

    async def test_hours_outside_the_window_are_rejected(self) -> None:
        """Reject a past hour older than Genesis' redemption window."""
        site_key = await self._site_key()
        stale = datetime.now(NZ_TIME_ZONE).date() - timedelta(days=90)

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_redeem_past(
                site_key, manual_start=f"{stale.isoformat()}T08:00:00"
            )

    async def test_a_run_past_midnight_is_rejected(self) -> None:
        """Reject a duration that would continue into the next day."""
        site_key = await self._site_key()

        with self.assertRaises(PowerShoutValidationError):
            await self.redemption.async_redeem_past(
                site_key,
                manual_start=f"{self.first_day.isoformat()}T23:00:00",
                duration=2,
            )

    # ── forward booking ──

    async def test_a_stored_booking_survives_an_error_response(self) -> None:
        """Accept a forward booking Genesis stored while answering an error."""
        await self._site_key()
        start = datetime.now(NZ_TIME_ZONE).replace(
            tzinfo=None, minute=0, second=0, microsecond=0
        ) + timedelta(hours=2)
        self.api.add_error = ApiError("boom", status=500)
        self.api.remote_bookings = [
            {"id": "booking-1", "startDateTime": start.strftime("%Y-%m-%dT%H:%M:%S")}
        ]

        result = await self.redemption.async_book_future(start, 1)

        self.assertEqual(result["duration_hours"], 1)

    async def test_a_missing_booking_still_reports_the_error(self) -> None:
        """Report failure when Genesis errored and stored nothing."""
        await self._site_key()
        start = datetime.now(NZ_TIME_ZONE).replace(
            tzinfo=None, minute=0, second=0, microsecond=0
        ) + timedelta(hours=2)
        self.api.add_error = ApiError("boom", status=500)
        self.api.remote_bookings = []

        with self.assertRaises(ApiError):
            await self.redemption.async_book_future(start, 1)
