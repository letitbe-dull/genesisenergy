# custom_components/genesisenergy/binary_sensor.py
from datetime import timedelta
from zoneinfo import ZoneInfo

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
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

    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_info = coordinator.device_info
        self._attr_name = "Power Shout Booking In Progress"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_powershout_booking_in_progress"
        )
        self._attr_icon = "mdi:flash"

    @property
    def is_on(self) -> bool:
        """Return True if the current time falls within a booking window."""
        now = dt_util.utcnow()
        for b in _all_bookings(self.coordinator):
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
                return True
        return False

    @property
    def extra_state_attributes(self) -> dict | None:
        """Expose the booking that is currently in progress, if any."""
        now = dt_util.utcnow()
        for b in _all_bookings(self.coordinator):
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
                return {"current_booking": b}
        return None


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
