# custom_components/genesisenergy/binary_sensor.py
from datetime import timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
)
from .coordinator import GenesisEnergyDataUpdateCoordinator

UTC = ZoneInfo("UTC")


def _all_bookings(coordinator: GenesisEnergyDataUpdateCoordinator) -> list[dict]:
    """Return the raw bookings list from the coordinator data."""
    bookings_data = coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS) or {}
    bookings = bookings_data.get("bookings", [])
    return [b for b in bookings if isinstance(b, dict)]


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensor entities."""
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[BinarySensorEntity] = []

    if coordinator.data.get(DATA_API_POWERSHOUT_BALANCE) is not None:
        entities.append(PowerShoutOffersAvailableBinarySensor(coordinator))

    if coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS) is not None:
        entities.append(PowerShoutBookingInProgressBinarySensor(coordinator))
        entities.append(PowerShoutBookingUpcomingBinarySensor(coordinator))

    async_add_entities(entities)


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
