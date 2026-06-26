# custom_components/genesisenergy/config_flow.py

import logging
from typing import Any, Mapping
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv

from .api import GenesisEnergyApi
from homeassistant.core import callback
from .const import (
    DOMAIN, INTEGRATION_NAME, CONF_ENABLE_AUTO_CORRECTION,
    CONF_ACCESS_TOKEN, CONF_ACCESS_TOKEN_EXPIRY, CONF_REFRESH_TOKEN, CONF_REFRESH_TOKEN_EXPIRY,
)
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)


def _token_data(api: GenesisEnergyApi) -> dict[str, Any]:
    """Map the API's token state onto config-entry data keys."""
    state = api.get_token_state()
    return {
        CONF_ACCESS_TOKEN: state["access_token"],
        CONF_ACCESS_TOKEN_EXPIRY: state["access_token_expiry"],
        CONF_REFRESH_TOKEN: state["refresh_token"],
        CONF_REFRESH_TOKEN_EXPIRY: state["refresh_token_expiry"],
    }

class GenesisEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Genesis Energy."""
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GenesisEnergyOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            api = GenesisEnergyApi(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])

            try:
                await api.async_login()
                _LOGGER.info("Config flow: Authentication successful.")
                # Persist the freshly obtained tokens so initial setup skips a second login.
                return self.async_create_entry(
                    title=INTEGRATION_NAME, data={**user_input, **_token_data(api)}
                )

            except InvalidAuth as e:
                _LOGGER.warning(f"Config flow failed with InvalidAuth: {e}")
                errors["base"] = "invalid_auth"
            except CannotConnect as e:
                _LOGGER.warning(f"Config flow failed with CannotConnect: {e}")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Config flow failed with an unexpected exception")
                errors["base"] = "unknown"
            finally:
                await api.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]):
        """Handle re-authentication when credentials/tokens become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None):
        """Ask the user to re-enter their password and re-validate."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            api = GenesisEnergyApi(reauth_entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            try:
                await api.async_login()
                _LOGGER.info("Config flow: Reauthentication successful.")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD], **_token_data(api)},
                )
            except InvalidAuth as e:
                _LOGGER.warning(f"Reauth failed with InvalidAuth: {e}")
                errors["base"] = "invalid_auth"
            except CannotConnect as e:
                _LOGGER.warning(f"Reauth failed with CannotConnect: {e}")
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Reauth failed with an unexpected exception")
                errors["base"] = "unknown"
            finally:
                await api.close()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            description_placeholders={"email": reauth_entry.data[CONF_EMAIL]},
            errors=errors,
        )

class GenesisEnergyOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the Genesis Energy integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # NOTE: In recent HA versions, self.config_entry is a property and cannot be set.
        # We simply pass here; the property will work automatically in async_step_init.
        pass

    async def async_step_init(self, user_input: dict | None = None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Default is False (Disabled)
        current_value = self.config_entry.options.get(CONF_ENABLE_AUTO_CORRECTION, False)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_ENABLE_AUTO_CORRECTION, default=current_value): bool,
            }),
        )