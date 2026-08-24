from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .api import GenesisEnergyApi
from .const import LOGGER
from .exceptions import (
    ApiError,
    GenesisEnergyError,
    PowerShoutUnavailableError,
    PowerShoutValidationError,
)

NZ_TIME_ZONE = ZoneInfo("Pacific/Auckland")
PAST_HOURS_TOGGLE = "powerShoutRedeemPastHours"


@dataclass(frozen=True, slots=True)
class HourCost:
    """Describe one recorded hour of electricity use."""

    start: str
    kwh: float
    cost: float

    def as_dict(self) -> dict[str, Any]:
        """Return the public hour fields."""
        return {
            "start_datetime": self.start,
            "kwh": round(self.kwh, 2),
            "cost": round(self.cost, 2),
        }


@dataclass(frozen=True, slots=True)
class RankedHour:
    """Describe one eligible past hour, ranked by what it would credit back."""

    start: str
    day: str
    time: str
    kwh: float
    cost: float
    recommendation_key: str | None
    genesis_rank: int | None

    def as_dict(self) -> dict[str, Any]:
        """Return the public ranked-hour fields."""
        return {
            "start_datetime": self.start,
            "day": self.day,
            "time": self.time,
            "kwh": round(self.kwh, 2),
            "cost": round(self.cost, 2),
            "recommendation_key": self.recommendation_key,
            "genesis_rank": self.genesis_rank,
        }


def build_ranked_hours(
    hours: Mapping[str, HourCost],
    recommendations: Sequence["PowerShoutRecommendation"],
    booked_starts: frozenset[str],
    limit: int,
) -> tuple[RankedHour, ...]:
    """Rank eligible hours by the credit they would return."""
    by_start = {item.date_time: (index, item) for index, item in enumerate(recommendations)}

    ranked: list[RankedHour] = []
    for key, hour in hours.items():
        # An hour already covered by a Power Shout cannot be redeemed again.
        if hour.cost <= 0 or key in booked_starts:
            continue
        index_item = by_start.get(key)
        try:
            parsed = datetime.strptime(key, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        ranked.append(
            RankedHour(
                start=key,
                day=parsed.strftime("%a %d %b"),
                time=_hour_label(parsed.hour),
                kwh=hour.kwh,
                cost=hour.cost,
                recommendation_key=index_item[1].key if index_item else None,
                genesis_rank=index_item[0] + 1 if index_item else None,
            )
        )

    ranked.sort(key=lambda item: (-item.cost, item.start))
    return tuple(ranked[:limit]) if limit > 0 else tuple(ranked)


def _hour_label(hour: int) -> str:
    """Return a 12-hour label for an hour of the day, e.g. 8am."""
    suffix = "am" if hour < 12 else "pm"
    display = hour % 12 or 12
    return f"{display}{suffix}"


@dataclass(frozen=True, slots=True)
class PowerShoutSite:
    """Describe an eligible Power Shout property."""

    key: str
    address: str
    site_id: str
    billing_account_id: str
    icp_number: str
    supply_agreement_id: str
    loyalty_account_id: str


@dataclass(frozen=True, slots=True)
class PowerShoutRecommendation:
    """Describe a Genesis-recommended retrospective hour."""

    key: str
    date_time: str
    day: str
    time: str

    def as_dict(self) -> dict[str, str]:
        """Return the public recommendation fields."""
        return {
            "key": self.key,
            "start_datetime": self.date_time,
            "day": self.day,
            "time": self.time,
        }


@dataclass(frozen=True, slots=True)
class PowerShoutRedemptionState:
    """Describe retrospective Power Shout availability for one property."""

    site: PowerShoutSite
    feature_enabled: bool | None
    past_days: int
    available_hours: int
    recommendations: tuple[PowerShoutRecommendation, ...]
    error: str | None = None
    error_detail: str | None = None
    ranked_hours: tuple[RankedHour, ...] = ()

    @property
    def has_recommendations(self) -> bool:
        """Return whether at least one past hour can be redeemed."""
        return (
            self.feature_enabled is True
            and self.past_days > 0
            and self.available_hours > 0
            and bool(self.recommendations or self.ranked_hours)
            and self.error is None
        )

    def public_attributes(self, config_entry_id: str) -> dict[str, Any]:
        """Return fields safe to expose through Home Assistant."""
        today = datetime.now(NZ_TIME_ZONE).date()
        earliest_date = (
            (today - timedelta(days=self.past_days)).isoformat()
            if self.past_days > 0
            else None
        )
        latest_date = (
            (today - timedelta(days=1)).isoformat()
            if self.past_days > 0
            else None
        )
        return {
            "config_entry_id": config_entry_id,
            "site_key": self.site.key,
            "property": self.site.address,
            "feature_enabled": self.feature_enabled,
            "past_days": self.past_days,
            "earliest_date": earliest_date,
            "latest_date": latest_date,
            "available_hours": self.available_hours,
            "recommendation_count": len(self.recommendations),
            "recommendations": [item.as_dict() for item in self.recommendations],
            "ranked_hours": [item.as_dict() for item in self.ranked_hours],
            "ranked_hour_count": len(self.ranked_hours),
            "error": self.error,
            "error_detail": self.error_detail,
        }


def _site_key(site_id: str, icp_number: str) -> str:
    """Return a stable opaque key for an eligible property."""
    value = f"{site_id}\0{icp_number}".encode()
    return hashlib.sha256(value).hexdigest()[:16]


def _local_datetime(value: datetime | str) -> datetime:
    """Normalize a datetime to a naive New Zealand local value."""
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError("Power Shout date must be a datetime or ISO string.")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(NZ_TIME_ZONE).replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _date_label(value: datetime) -> str:
    """Format a portable short date label."""
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')}"


def _time_label(value: datetime) -> str:
    """Format a portable lowercase time label."""
    return value.strftime("%I:%M%p").lstrip("0").lower()


def _parse_sites(payload: Mapping[str, Any] | None) -> dict[str, PowerShoutSite]:
    """Extract eligible electricity properties from Genesis data."""
    if not isinstance(payload, Mapping):
        return {}
    loyalty_account_id = str(payload.get("loyaltyAccountId") or "")
    eligible_accounts = payload.get("eligibleBillingAccounts")
    if not loyalty_account_id or not isinstance(eligible_accounts, list):
        return {}

    sites: dict[str, PowerShoutSite] = {}
    for account in eligible_accounts:
        if not isinstance(account, Mapping):
            continue
        account_sites = account.get("billingAccountSites")
        if not isinstance(account_sites, list):
            continue
        for raw_site in account_sites:
            if not isinstance(raw_site, Mapping):
                continue
            site_id = str(raw_site.get("id") or "")
            supply_points = raw_site.get("supplyPoints")
            if not site_id or not isinstance(supply_points, list):
                continue
            valid_supply_points = [
                item for item in supply_points if isinstance(item, Mapping)
            ]
            if not valid_supply_points:
                continue
            supply_point = next(
                (
                    item
                    for item in valid_supply_points
                    if item.get("supplyAgreementId")
                    and str(item["supplyAgreementId"]) in site_id
                ),
                valid_supply_points[0],
            )
            icp_number = str(supply_point.get("id") or "")
            supply_agreement_id = str(
                supply_point.get("supplyAgreementId") or ""
            )
            if not icp_number or not supply_agreement_id:
                continue
            billing_account_id = str(
                raw_site.get("billingAccountId") or account.get("id") or ""
            )
            key = _site_key(site_id, icp_number)
            sites[key] = PowerShoutSite(
                key=key,
                address=str(
                    raw_site.get("address")
                    or supply_point.get("nickname")
                    or "Electricity property"
                ),
                site_id=site_id,
                billing_account_id=billing_account_id,
                icp_number=icp_number,
                supply_agreement_id=supply_agreement_id,
                loyalty_account_id=loyalty_account_id,
            )
    return sites


def _past_feature_enabled(metadata: Mapping[str, Any] | None) -> bool | None:
    """Read the retrospective Power Shout release toggle."""
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("value")
    if not isinstance(value, Mapping):
        return None
    toggles = value.get("toggles")
    if not isinstance(toggles, Mapping):
        return None
    release = toggles.get("release")
    if not isinstance(release, list):
        return None
    for toggle in release:
        if isinstance(toggle, Mapping) and toggle.get("id") == PAST_HOURS_TOGGLE:
            return bool(toggle.get("enabled"))
    return None


def _positive_int(value: Any) -> int:
    """Return a non-negative integer from API data."""
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _recommendation_key(date_time: str) -> str:
    """Return an opaque key for a recommended hour."""
    return hashlib.sha256(date_time.encode()).hexdigest()[:16]


def _recommendations(payload: Mapping[str, Any]) -> tuple[PowerShoutRecommendation, ...]:
    """Normalize Genesis recommended hours."""
    raw_items = payload.get("recommendedHours")
    if not isinstance(raw_items, list):
        return ()
    items: list[PowerShoutRecommendation] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping) or not raw_item.get("dateTime"):
            continue
        try:
            local_value = _local_datetime(raw_item["dateTime"])
        except (TypeError, ValueError):
            continue
        date_time = local_value.strftime("%Y-%m-%dT%H:%M:%S")
        items.append(
            PowerShoutRecommendation(
                key=_recommendation_key(date_time),
                date_time=date_time,
                day=str(raw_item.get("day") or _date_label(local_value)),
                time=str(raw_item.get("time") or _time_label(local_value)),
            )
        )
    return tuple(items)


def _voucher_numbers(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract private voucher numbers from a recommendation response."""
    balance = payload.get("availableBalance")
    if not isinstance(balance, Mapping):
        return ()
    vouchers = balance.get("vouchers")
    if not isinstance(vouchers, list):
        return ()
    return tuple(
        str(voucher["number"])
        for voucher in vouchers
        if isinstance(voucher, Mapping) and voucher.get("number")
    )


def _available_hours(payload: Mapping[str, Any]) -> int:
    """Extract the retrospective balance from a recommendation response."""
    balance = payload.get("availableBalance")
    if not isinstance(balance, Mapping):
        return 0
    return _positive_int(balance.get("hours"))


def _error_message(error: GenesisEnergyError) -> tuple[str, str]:
    """Map an API failure to a stable code and safe message."""
    if isinstance(error, ApiError):
        if error.error_type == "/error/add_booking/time_lapsed":
            return "time_lapsed", "That hour can no longer be redeemed."
        if error.error_type == "/error/add_booking/duplicate_booking":
            return "duplicate_booking", "That hour already has a Power Shout."
        return (
            error.error_type or "api_error",
            "Genesis could not apply that Power Shout.",
        )
    return "connection_error", "Genesis could not be reached."


class PowerShoutRedemption:
    """Coordinate Genesis Power Shout booking policies."""

    def __init__(self, api: GenesisEnergyApi) -> None:
        self._api = api
        self._sites: dict[str, PowerShoutSite] = {}
        self._states: dict[str, PowerShoutRedemptionState] = {}
        self._vouchers: dict[str, tuple[str, ...]] = {}
        self._lock = asyncio.Lock()

    @property
    def states(self) -> Mapping[str, PowerShoutRedemptionState]:
        """Return the latest property states."""
        return self._states

    async def async_load_states(
        self,
        metadata: Mapping[str, Any] | None,
        eligible_accounts: Mapping[str, Any] | None,
    ) -> dict[str, PowerShoutRedemptionState]:
        """Load retrospective state for all eligible properties."""
        async with self._lock:
            sites = _parse_sites(eligible_accounts)
            feature_enabled = _past_feature_enabled(metadata)
            self._sites = sites
            self._vouchers = {}

            if feature_enabled is False:
                self._states = {
                    key: PowerShoutRedemptionState(
                        site=site,
                        feature_enabled=feature_enabled,
                        past_days=0,
                        available_hours=0,
                        recommendations=(),
                    )
                    for key, site in sites.items()
                }
                return dict(self._states)

            try:
                setup = await self._api.get_powershout_setup()
            except GenesisEnergyError:
                self._states = {
                    key: PowerShoutRedemptionState(
                        site=site,
                        feature_enabled=feature_enabled,
                        past_days=0,
                        available_hours=0,
                        recommendations=(),
                        error="setup_unavailable",
                    )
                    for key, site in sites.items()
                }
                return dict(self._states)

            past_days = (
                _positive_int(setup.get("noOfPastDaysToRedeem"))
                if isinstance(setup, Mapping)
                else 0
            )
            if past_days <= 0:
                self._states = {
                    key: PowerShoutRedemptionState(
                        site=site,
                        feature_enabled=True,
                        past_days=0,
                        available_hours=0,
                        recommendations=(),
                    )
                    for key, site in sites.items()
                }
                return dict(self._states)
            results = await asyncio.gather(
                *(self._async_load_site(site, past_days) for site in sites.values())
            )
            self._states = {state.site.key: state for state, _ in results}
            self._vouchers = {
                state.site.key: vouchers for state, vouchers in results
            }
            return dict(self._states)

    async def _async_load_site(
        self, site: PowerShoutSite, past_days: int
    ) -> tuple[PowerShoutRedemptionState, tuple[str, ...]]:
        """Load recommendation state for one property."""
        if not site.billing_account_id:
            return (
                PowerShoutRedemptionState(
                    site=site,
                    feature_enabled=True,
                    past_days=past_days,
                    available_hours=0,
                    recommendations=(),
                    error="property_identifiers_missing",
                ),
                (),
            )
        try:
            response = await self._api.get_powershout_recommended_hours(
                account_id=site.loyalty_account_id,
                billing_account_id=site.billing_account_id,
                icp_number=site.icp_number,
                supply_agreement_id=site.supply_agreement_id,
            )
        except GenesisEnergyError as err:
            status = getattr(err, "status", None)
            return (
                PowerShoutRedemptionState(
                    site=site,
                    feature_enabled=True,
                    past_days=past_days,
                    available_hours=0,
                    recommendations=(),
                    error="recommendations_unavailable",
                    error_detail=f"HTTP {status}" if status else str(err) or None,
                ),
                (),
            )
        if not isinstance(response, Mapping):
            return (
                PowerShoutRedemptionState(
                    site=site,
                    feature_enabled=True,
                    past_days=past_days,
                    available_hours=0,
                    recommendations=(),
                    error="recommendations_invalid",
                ),
                (),
            )
        recommendations = _recommendations(response)
        vouchers = _voucher_numbers(response)
        available_hours = _available_hours(response)
        error = (
            "recommendation_balance_invalid"
            if available_hours > 0 and not vouchers
            else None
        )
        return (
            PowerShoutRedemptionState(
                site=site,
                feature_enabled=True,
                past_days=past_days,
                available_hours=available_hours,
                recommendations=recommendations,
                error=error,
            ),
            vouchers,
        )

    async def _async_booking_ids(self) -> set[str] | None:
        """Return current Genesis booking ids, or None if they cannot be read."""
        try:
            data = await self._api.get_powershout_bookings()
        except GenesisEnergyError:
            return None
        bookings = data.get("bookings") if isinstance(data, Mapping) else None
        if not isinstance(bookings, list):
            return None
        return {
            str(item["id"])
            for item in bookings
            if isinstance(item, Mapping) and item.get("id")
        }

    async def _async_booking_starts(self) -> set[datetime] | None:
        """Return current booking start hours, or None if they cannot be read."""
        try:
            data = await self._api.get_powershout_bookings()
        except GenesisEnergyError:
            return None
        bookings = data.get("bookings") if isinstance(data, Mapping) else None
        if not isinstance(bookings, list):
            return None
        starts: set[datetime] = set()
        for item in bookings:
            if not isinstance(item, Mapping) or not item.get("startDateTime"):
                continue
            try:
                starts.add(_local_datetime(str(item["startDateTime"])))
            except (TypeError, ValueError):
                continue
        return starts

    async def async_cancel_booking(
        self, booking_id: str, site_key: str | None = None
    ) -> None:
        """Cancel an upcoming Power Shout booking."""
        if not booking_id:
            raise PowerShoutValidationError("A booking is required to cancel.")
        site = self.resolve_site(site_key)
        if not site.loyalty_account_id:
            raise PowerShoutUnavailableError(
                "That property is missing the account details Genesis needs."
            )
        try:
            # Genesis names this field billingAccountId but its own client sends
            # the loyalty account id; the billing account id is rejected.
            await self._api.delete_powershout_booking(
                booking_id=booking_id,
                billing_account_id=site.loyalty_account_id,
            )
        except ApiError as err:
            # Genesis answers /error/non_standard_error on requests it has
            # already applied, so trust the booking list over the status code.
            ids = await self._async_booking_ids()
            if ids is not None and booking_id not in ids:
                return
            LOGGER.warning(
                "Power Shout cancel rejected. site_id=%s billing_account_id=%s "
                "icp=%s supply_agreement_id=%s loyalty_account_id=%s booking_id=%s",
                site.site_id,
                site.billing_account_id,
                site.icp_number,
                site.supply_agreement_id,
                site.loyalty_account_id,
                booking_id,
            )
            raise PowerShoutUnavailableError(
                str(err) or "Genesis could not cancel that Power Shout."
            ) from err
        except GenesisEnergyError as err:
            raise PowerShoutUnavailableError("Genesis could not be reached.") from err

    def resolve_site(self, site_key: str | None = None) -> PowerShoutSite:
        """Resolve one property or reject an ambiguous selection."""
        if site_key:
            if site := self._sites.get(site_key):
                return site
            raise PowerShoutValidationError("The selected Power Shout property is unavailable.")
        if len(self._sites) == 1:
            return next(iter(self._sites.values()))
        if not self._sites:
            raise PowerShoutUnavailableError("No Power Shout electricity property is available.")
        raise PowerShoutValidationError("Select which property should use the Power Shout.")

    async def async_refresh_site(self, site_key: str) -> PowerShoutRedemptionState:
        """Refresh and return one retrospective property state."""
        metadata, eligible_accounts = await asyncio.gather(
            self._api.get_initialize_metadata(),
            self._api.get_powershout_info(),
        )
        states = await self.async_load_states(metadata, eligible_accounts)
        if state := states.get(site_key):
            return state
        raise PowerShoutValidationError("The selected Power Shout property is unavailable.")

    async def async_redeem_past(
        self,
        site_key: str,
        recommendation_keys: Sequence[str] | None = None,
        manual_start: datetime | str | Sequence[datetime | str] | None = None,
        duration: int = 1,
    ) -> dict[str, Any]:
        """Redeem selected retrospective Power Shout hours."""
        state = await self.async_refresh_site(site_key)
        if state.feature_enabled is not True or state.past_days <= 0:
            raise PowerShoutUnavailableError("Past-hour Power Shout redemption is unavailable.")
        if state.error and recommendation_keys:
            raise PowerShoutUnavailableError(
                "Genesis could not load past-hour recommendations."
            )
        if duration < 1 or duration > 4:
            raise PowerShoutValidationError("Duration must be between 1 and 4 hours.")

        if manual_start is None:
            manual_starts: list[datetime | str] = []
        elif isinstance(manual_start, (list, tuple)):
            manual_starts = list(manual_start)
        else:
            manual_starts = [manual_start]

        keys = tuple(recommendation_keys or ())
        if bool(keys) == bool(manual_starts):
            raise PowerShoutValidationError(
                "Choose either Genesis recommendations or past hours by time."
            )
        if len(manual_starts) > 1 and duration != 1:
            raise PowerShoutValidationError(
                "Selecting several past hours redeems one hour each."
            )
        if len(set(keys)) != len(keys):
            raise PowerShoutValidationError(
                "Each selected recommendation must be unique."
            )
        if keys and duration != 1:
            raise PowerShoutValidationError(
                "Genesis recommended selections must each be one hour."
            )

        recommendations_by_key = {
            item.key: item for item in state.recommendations
        }
        missing_keys = [key for key in keys if key not in recommendations_by_key]
        if missing_keys:
            raise PowerShoutValidationError(
                "A selected recommendation is stale or no longer available."
            )
        if keys:
            starts: list[datetime | str] = [
                recommendations_by_key[key].date_time for key in keys
            ]
        else:
            starts = list(manual_starts)

        try:
            local_starts = [_local_datetime(value) for value in starts]
        except (TypeError, ValueError) as err:
            raise PowerShoutValidationError(
                "Every selected Power Shout hour must be a valid date and time."
            ) from err
        if len({value for value in local_starts}) != len(local_starts):
            raise PowerShoutValidationError("Each selected past hour must be unique.")
        if any(
            value.minute or value.second or value.microsecond for value in local_starts
        ):
            raise PowerShoutValidationError("Power Shout hours must start on the hour.")
        if any(value.hour + duration > 24 for value in local_starts):
            raise PowerShoutValidationError("A Power Shout cannot continue past midnight.")

        today = datetime.now(NZ_TIME_ZONE).date()
        earliest = today - timedelta(days=state.past_days)
        latest = today - timedelta(days=1)
        if any(value.date() < earliest or value.date() > latest for value in local_starts):
            raise PowerShoutValidationError(
                f"Choose a date from {earliest.isoformat()} to {latest.isoformat()}."
            )

        start_strings = [value.strftime("%Y-%m-%dT%H:%M:%S") for value in local_starts]
        recommended_batch = bool(keys)

        hours_required = len(start_strings) * duration
        # A failed recommendations call leaves the balance unknown; the
        # per-date voucher check below is the authority either way.
        if not state.error and state.available_hours < hours_required:
            raise PowerShoutUnavailableError("There are not enough Power Shout hours available.")
        site = state.site
        if recommended_batch:
            recommendation_vouchers = self._vouchers.get(site_key, ())
            if len(recommendation_vouchers) < len(start_strings):
                raise PowerShoutUnavailableError(
                    "Genesis did not return enough Power Shout vouchers."
                )
            tasks = [
                self._async_redeem_one(
                    site=site,
                    start_date=start_date,
                    duration=1,
                    vouchers=[recommendation_vouchers[index]],
                    recommendation_key=keys[index],
                )
                for index, start_date in enumerate(start_strings)
            ]
        else:
            # Vouchers are issued per date, so fetch each distinct date once and
            # hand out its vouchers across the hours chosen on that date.
            unique_dates = sorted({value.date() for value in local_starts})
            responses = await asyncio.gather(
                *(
                    self._api.get_powershout_vouchers_for_date(
                        f"{value.isoformat()}T00:00:00.000Z", site.icp_number
                    )
                    for value in unique_dates
                ),
                return_exceptions=True,
            )
            vouchers_by_date: dict[date, list[Any]] = {}
            for value, response in zip(unique_dates, responses):
                if isinstance(response, Exception) or not isinstance(response, Mapping):
                    raise PowerShoutUnavailableError(
                        "Genesis could not confirm the hours available for that date."
                    )
                items = response.get("vouchers", [])
                vouchers_by_date[value] = list(items) if isinstance(items, list) else []

            tasks = []
            for local_value, start_date in zip(local_starts, start_strings):
                pool = vouchers_by_date[local_value.date()]
                if len(pool) < duration:
                    raise PowerShoutUnavailableError(
                        "There are not enough Power Shout hours available for that date."
                    )
                tasks.append(
                    self._async_redeem_one(
                        site=site,
                        start_date=start_date,
                        duration=duration,
                        vouchers=pool[:duration],
                        recommendation_key=None,
                    )
                )
                del pool[:duration]
        attempts = await asyncio.gather(*tasks)
        succeeded = [attempt for attempt in attempts if attempt["success"]]
        failed = [attempt for attempt in attempts if not attempt["success"]]
        return {
            "attempted_count": len(attempts),
            "succeeded": succeeded,
            "failed": failed,
            "history_may_be_pending": bool(succeeded),
        }

    async def _async_redeem_one(
        self,
        *,
        site: PowerShoutSite,
        start_date: str,
        duration: int,
        vouchers: list[Any],
        recommendation_key: str | None,
    ) -> dict[str, Any]:
        """Redeem one retrospective request."""
        try:
            await self._api.add_powershout_booking(
                start_date_str=start_date,
                duration=duration,
                supply_agreement_id=site.supply_agreement_id,
                supply_point_id=site.icp_number,
                loyalty_account_id=site.loyalty_account_id,
                eco_hours=[],
                vouchers=vouchers,
            )
        except GenesisEnergyError as error:
            code, message = _error_message(error)
            result = {
                "start_datetime": start_date,
                "duration_hours": duration,
                "success": False,
                "code": code,
                "message": message,
            }
        else:
            result = {
                "start_datetime": start_date,
                "duration_hours": duration,
                "success": True,
            }
        if recommendation_key:
            result["recommendation_key"] = recommendation_key
        return result

    async def async_book_future(
        self,
        start: datetime,
        duration: int,
        site_key: str | None = None,
    ) -> dict[str, Any]:
        """Book one current or future Power Shout window."""
        eligible_accounts = await self._api.get_powershout_info()
        self._sites = _parse_sites(eligible_accounts)
        site = self.resolve_site(site_key)
        local_start = _local_datetime(start)
        if duration < 1 or duration > 4:
            raise PowerShoutValidationError("Duration must be between 1 and 4 hours.")
        if local_start.minute or local_start.second or local_start.microsecond:
            raise PowerShoutValidationError("Power Shout hours must start on the hour.")
        current_hour = datetime.now(NZ_TIME_ZONE).replace(
            tzinfo=None,
            minute=0,
            second=0,
            microsecond=0,
        )
        if local_start < current_hour:
            raise PowerShoutValidationError(
                "Use the past-hour action for an earlier Power Shout."
            )
        if local_start.hour + duration > 24:
            raise PowerShoutValidationError("A Power Shout cannot continue past midnight.")

        selected_date = f"{local_start.date().isoformat()}T00:00:00.000Z"
        voucher_data, generation_mix = await asyncio.gather(
            self._api.get_powershout_vouchers_for_date(
                selected_date, site.icp_number
            ),
            self._api.get_generation_mix(),
            return_exceptions=True,
        )
        if isinstance(voucher_data, Exception):
            raise PowerShoutUnavailableError(
                "Genesis could not load Power Shout vouchers."
            ) from voucher_data
        vouchers = (
            voucher_data.get("vouchers", [])
            if isinstance(voucher_data, Mapping)
            else []
        )
        if not isinstance(vouchers, list) or len(vouchers) < duration:
            raise PowerShoutUnavailableError("There are not enough Power Shout hours available.")
        eco_hours = (
            self._eco_hours(generation_mix, local_start, duration)
            if not isinstance(generation_mix, Exception)
            else []
        )
        try:
            await self._api.add_powershout_booking(
                start_date_str=local_start.strftime("%Y-%m-%dT%H:%M:%S"),
                duration=duration,
                supply_agreement_id=site.supply_agreement_id,
                supply_point_id=site.icp_number,
                loyalty_account_id=site.loyalty_account_id,
                eco_hours=eco_hours,
                vouchers=vouchers[:duration],
            )
        except ApiError:
            # Genesis has been seen storing a booking and answering 500 anyway;
            # reporting failure here would invite a duplicate booking.
            starts = await self._async_booking_starts()
            if starts is None or local_start not in starts:
                raise
        return {
            "start_datetime": local_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_hours": duration,
            "property": site.address,
        }

    @staticmethod
    def _eco_hours(
        generation_mix: Any, start: datetime, duration: int
    ) -> list[dict[str, Any]]:
        """Build Genesis eco-hour metadata for a future booking."""
        if not isinstance(generation_mix, list):
            return []
        day_data = next(
            (
                item
                for item in generation_mix
                if isinstance(item, Mapping)
                and item.get("Day") == start.date().isoformat()
            ),
            None,
        )
        if not isinstance(day_data, Mapping):
            return []
        hourly = day_data.get("HourlyBreakdown")
        if not isinstance(hourly, list):
            return []
        values: list[dict[str, Any]] = []
        for hour in range(start.hour, start.hour + duration):
            item = hourly[hour] if hour < len(hourly) else None
            values.append(
                {
                    "hour": hour,
                    "ecoFriendly": bool(
                        item.get("EcoFriendly")
                        if isinstance(item, Mapping)
                        else False
                    ),
                }
            )
        return values
