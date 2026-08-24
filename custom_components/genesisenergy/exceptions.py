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
    """Error returned by the Genesis API."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_type: str | None = None,
        response_data: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.response_data = response_data


class PowerShoutValidationError(GenesisEnergyError):
    """Error raised for an invalid Power Shout selection."""


class PowerShoutUnavailableError(GenesisEnergyError):
    """Error raised when Power Shout cannot be used."""
