# custom_components/genesisenergy/binary_sensor.py
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import voluptuous as vol

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    LOGGER,
    DATA_API_POWERSHOUT_BALANCE,
    DATA_API_POWERSHOUT_BOOKINGS,
    DATA_POWERSHOUT_REDEMPTION_STATES,
    ATTR_DURATION_HOURS,
    ATTR_RECOMMENDATION_KEYS,
    ATTR_START_DATETIME,
    SERVICE_REDEEM_POWERSHOUT,
)
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .exceptions import (
    GenesisEnergyError,
    PowerShoutValidationError,
)
from .powershout import PowerShoutRedemptionState

UTC = ZoneInfo("UTC")


def _all_bookings(coordinator: GenesisEnergyDataUpdateCoordinator) -> list[dict]:
    """Return the raw bookings list from the coordinator data."""
    bookings_data = coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS) or {}
    bookings = bookings_data.get("bookings", [])
    return [b for b in bookings if isinstance(b, dict)]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor entities."""
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    entities: list[BinarySensorEntity] = []

    if coordinator.data.get(DATA_API_POWERSHOUT_BALANCE) is not None:
        entities.append(PowerShoutOffersAvailableBinarySensor(coordinator))

    if coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS) is not None:
        entities.append(PowerShoutBookingInProgressBinarySensor(coordinator))
        entities.append(PowerShoutBookingUpcomingBinarySensor(coordinator))

    async_add_entities(entities)

    known_site_keys: set[str] = set()

    @callback
    def _add_redemption_entities() -> None:
        """Add property entities discovered after platform setup."""
        states = coordinator.data.get(DATA_POWERSHOUT_REDEMPTION_STATES) or {}
        new_states = [
            state
            for state in states.values()
            if isinstance(state, PowerShoutRedemptionState)
            and state.site.key not in known_site_keys
        ]
        new_entities = [
            PowerShoutHighestSavingsBinarySensor(
                coordinator,
                state.site.key,
                multiple_sites=len(states) > 1,
            )
            for state in new_states
        ]
        known_site_keys.update(state.site.key for state in new_states)
        if new_entities:
            async_add_entities(new_entities)

    _add_redemption_entities()
    config_entry.async_on_unload(
        coordinator.async_add_listener(_add_redemption_entities)
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_REDEEM_POWERSHOUT,
        {
            vol.Optional(ATTR_RECOMMENDATION_KEYS): [cv.string],
            vol.Optional(ATTR_START_DATETIME): vol.Any(
                cv.datetime, vol.All(cv.ensure_list, [cv.datetime])
            ),
            vol.Optional(ATTR_DURATION_HOURS, default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=4)
            ),
        },
        _async_redeem_powershout,
        supports_response=SupportsResponse.OPTIONAL,
    )


async def _async_redeem_powershout(
    entity: BinarySensorEntity, call: ServiceCall
) -> ServiceResponse:
    """Redeem past Power Shout hours through a recommendation entity."""
    if not isinstance(entity, PowerShoutHighestSavingsBinarySensor):
        raise ServiceValidationError(
            "Select a Genesis Power Shout Highest Savings entity."
        )
    try:
        return await entity.async_redeem(
            call.data.get(ATTR_RECOMMENDATION_KEYS),
            call.data.get(ATTR_START_DATETIME),
            call.data[ATTR_DURATION_HOURS],
        )
    except PowerShoutValidationError as err:
        raise ServiceValidationError(str(err)) from err
    except GenesisEnergyError as err:
        raise HomeAssistantError(str(err)) from err


class PowerShoutHighestSavingsBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Expose Genesis-ranked retrospective Power Shout hours."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:history"

    def __init__(
        self,
        coordinator: GenesisEnergyDataUpdateCoordinator,
        site_key: str,
        *,
        multiple_sites: bool,
    ) -> None:
        """Initialize the recommendation sensor."""
        super().__init__(coordinator)
        self._site_key = site_key
        state = self._redemption_state
        address = state.site.address if state else "Power Shout"
        self._attr_device_info = coordinator.device_info
        self._attr_name = (
            f"Power Shout Highest Savings - {address}"
            if multiple_sites
            else "Power Shout Highest Savings"
        )
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_powershout_highest_savings_{site_key}"
        )

    @property
    def _redemption_state(self) -> PowerShoutRedemptionState | None:
        """Return the current property state."""
        states = self.coordinator.data.get(DATA_POWERSHOUT_REDEMPTION_STATES) or {}
        state = states.get(self._site_key)
        return state if isinstance(state, PowerShoutRedemptionState) else None

    @property
    def available(self) -> bool:
        """Return whether a property state exists for this site."""
        # A Genesis error stays readable in the attributes: going unavailable
        # drops them, which hides the reason and the whole past-hours UI.
        return super().available and self._redemption_state is not None

    @property
    def is_on(self) -> bool:
        """Return whether Genesis has a redeemable recommendation."""
        state = self._redemption_state
        return bool(state and state.has_recommendations)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose display-safe recommendation data."""
        state = self._redemption_state
        if not state:
            return None
        return state.public_attributes(self.coordinator.config_entry.entry_id)

    async def async_redeem(
        self,
        recommendation_keys: list[str] | None,
        manual_start: datetime | list[datetime] | None,
        duration: int,
    ) -> dict[str, Any]:
        """Redeem selected past hours and refresh coordinator state."""
        result = await self.coordinator.powershout.async_redeem_past(
            self._site_key,
            recommendation_keys=recommendation_keys,
            manual_start=manual_start,
            duration=duration,
        )
        # Genesis does not reliably reject an hour that was already redeemed, so
        # this only catches the cases where it happens to say so.
        already = [
            item
            for item in result["failed"]
            if item.get("code") == "duplicate_booking"
        ]
        if result["succeeded"] or already:
            # A redeemed hour can cover more than one slot, and Genesis will keep
            # recommending every one of them until we exclude them ourselves.
            redeemed: list[str] = []
            for item in [*result["succeeded"], *already]:
                start = item.get("start_datetime")
                if not start:
                    continue
                try:
                    first = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S")
                except (TypeError, ValueError):
                    continue
                for offset in range(max(1, int(item.get("duration_hours") or 1))):
                    redeemed.append(
                        (first + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%S")
                    )
            await self.coordinator.async_record_redeemed(redeemed)
        if result["succeeded"] or already:
            await self.coordinator.async_request_refresh()
        return result


class PowerShoutOffersAvailableBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that indicates if any Power Shout offers are available."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Offers Available"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_powershout_offers_available"
        self._attr_icon = "mdi:gift-outline"

    @property
    def is_on(self) -> bool:
        """Return True if there are active offers."""
        data = self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE) or {}
        count = data.get("active_offers_count", 0)
        return count > 0

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the raw balance data for debugging and dashboards."""
        return self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE, {})


class PowerShoutBookingInProgressBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON while a Power Shout booking is currently running."""

    _attr_has_entity_name = True

    # A booking can be added (or retroactively added to the current hour) at any
    # minute, and is only discoverable by re-fetching, so poll the bookings endpoint
    # on this interval to pick up the ON edge. The fetch is cheap: api.async_login()
    # only hits the network when the cached token is near expiry (api.py:266-270).
    _POLL_INTERVAL = timedelta(minutes=2)

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Booking In Progress"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_powershout_booking_in_progress"
        )
        self._attr_icon = "mdi:flash"
        # Own copy of the bookings list, kept fresher than the hourly coordinator
        # poll so this sensor doesn't stay ON for up to an hour after a window ends.
        self._bookings: list[dict] = _all_bookings(coordinator)

    async def async_added_to_hass(self) -> None:
        """Schedule the bookings refreshes once the entity is live."""
        await super().async_added_to_hass()
        # ON edge: catch bookings added mid-hour (including ones retroactively
        # applied to the current hour) between the hourly coordinator polls.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._async_refresh_bookings, self._POLL_INTERVAL
            )
        )
        # OFF edge: windows always start and end on the hour, so a refresh exactly
        # at :00 flips the sensor off the moment a window ends (and a fresh fetch
        # there also catches a booking added right on the boundary).
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._async_refresh_bookings, minute=0, second=0
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the local cache from the hourly coordinator poll."""
        self._bookings = _all_bookings(self.coordinator)
        super()._handle_coordinator_update()

    async def _async_refresh_bookings(self, now=None) -> None:
        """Re-fetch just the bookings list and rewrite state.

        State is always rewritten, even if the fetch fails: is_on is a local clock
        check against the cached windows, so the OFF edge still fires at :00 offline.
        """
        try:
            await self.coordinator.api.async_login()
            data = await self.coordinator.api.get_powershout_bookings()
            if isinstance(data, dict):
                self._bookings = [
                    b for b in data.get("bookings", []) if isinstance(b, dict)
                ]
        except Exception as err:  # noqa: BLE001 - keep the timer alive on any error
            LOGGER.debug(
                "Power Shout in-progress refresh failed, recomputing from cache: %s",
                err,
            )
        self.async_write_ha_state()

    @property
    def _active_booking(self) -> dict | None:
        """Return the cached booking whose window currently contains now, if any."""
        now = dt_util.utcnow()
        for b in self._bookings:
            start_raw = b.get("startDateTime")
            if not start_raw:
                continue
            try:
                start = dt_util.parse_datetime(start_raw)
                if start is None:
                    continue
                start = start.astimezone(UTC)
                duration = float(b.get("duration") or 1)
            except (ValueError, TypeError):
                continue
            if start <= now < start + timedelta(hours=duration):
                return b
        return None

    @property
    def is_on(self) -> bool:
        """Return True if the current time falls within a booking window."""
        return self._active_booking is not None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the booking that is currently in progress, if any."""
        booking = self._active_booking
        return {"current_booking": booking} if booking is not None else None


class PowerShoutBookingUpcomingBinarySensor(
    CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON when at least one future Power Shout booking exists."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Booking Upcoming"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_powershout_booking_upcoming"
        )
        self._attr_icon = "mdi:calendar-clock"

    def _upcoming(self) -> list[dict]:
        """Return bookings whose start time is still in the future, soonest first."""
        now = dt_util.utcnow()
        upcoming = []
        for b in _all_bookings(self.coordinator):
            start_raw = b.get("startDateTime")
            if not start_raw:
                continue
            try:
                start = dt_util.parse_datetime(start_raw)
                if start is None:
                    continue
            except (ValueError, TypeError):
                continue
            if start.astimezone(UTC) > now:
                upcoming.append(b)
        upcoming.sort(key=lambda b: b["startDateTime"])
        return upcoming

    @property
    def is_on(self) -> bool:
        """Return True if there is at least one upcoming booking."""
        return bool(self._upcoming())

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the next booking's start time and upcoming count."""
        upcoming = self._upcoming()
        if not upcoming:
            return None
        return {
            "upcoming_count": len(upcoming),
            "next_booking_start": upcoming[0].get("startDateTime"),
        }
