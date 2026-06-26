# custom_components/genesisenergy/exceptions.py

from homeassistant.exceptions import HomeAssistantError

class GenesisEnergyError(HomeAssistantError):
    """Base class for Genesis Energy integration errors."""

class CannotConnect(GenesisEnergyError):
    """Error to indicate we cannot connect."""

class InvalidAuth(GenesisEnergyError):
    """Error to indicate there is invalid auth."""

class ApiError(GenesisEnergyError):
    """Generic API Error."""