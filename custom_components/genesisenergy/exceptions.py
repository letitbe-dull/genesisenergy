# custom_components/genesisenergy/exceptions.py

try:
    from homeassistant.exceptions import HomeAssistantError
except ModuleNotFoundError:
    # Allows standalone dev probes (e.g. scripts/watch_bookings.py) to import
    # api.py outside a Home Assistant runtime. Inside HA this branch never runs.
    class HomeAssistantError(Exception):  # type: ignore[no-redef]
        """Fallback base when Home Assistant isn't installed."""

class GenesisEnergyError(HomeAssistantError):
    """Base class for Genesis Energy integration errors."""

class CannotConnect(GenesisEnergyError):
    """Error to indicate we cannot connect."""

class InvalidAuth(GenesisEnergyError):
    """Error to indicate there is invalid auth."""

class ApiError(GenesisEnergyError):
    """Generic API Error."""