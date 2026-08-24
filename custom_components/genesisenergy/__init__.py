# custom_components/genesisenergy/__init__.py

from functools import partial
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import (
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.components.persistent_notification import async_create
from homeassistant.components.http import StaticPathConfig
import homeassistant.components.lovelace as lovelace_component

from .const import (
    DOMAIN, PLATFORMS, LOGGER, CONF_EMAIL,
    SERVICE_ADD_POWERSHOUT_BOOKING, ATTR_START_DATETIME, ATTR_DURATION_HOURS,
    DATA_API_POWERSHOUT_OFFERS,
    SERVICE_BACKFILL_STATISTICS, ATTR_DAYS_TO_FETCH, ATTR_FUEL_TYPE,
    SERVICE_FORCE_UPDATE, DATA_API_BILLING_PLANS,
    SERVICE_ACCEPT_POWERSHOUT_OFFER, ATTR_OFFER_ID, ATTR_SITE_KEY,
    SERVICE_CANCEL_POWERSHOUT_BOOKING, ATTR_BOOKING_ID,
    ATTR_CONFIG_ENTRY_ID,
)
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .exceptions import (
    GenesisEnergyError,
    PowerShoutValidationError,
)

_WWW_PATH_REGISTERED: bool = False
_CARD_FILENAME = "powershout-card.js"

ATTR_FORCE_OVERWRITE = "force_overwrite"

SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING = vol.Schema({
    vol.Required(ATTR_START_DATETIME): cv.datetime,
    vol.Required(ATTR_DURATION_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
    vol.Optional(ATTR_SITE_KEY): cv.string,
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
})

SERVICE_SCHEMA_ACCEPT_POWERSHOUT_OFFER = vol.Schema({
    vol.Required(ATTR_OFFER_ID): cv.string,
})

SERVICE_SCHEMA_CANCEL_POWERSHOUT_BOOKING = vol.Schema({
    vol.Required(ATTR_BOOKING_ID): cv.string,
    vol.Optional(ATTR_SITE_KEY): cv.string,
    vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
})

SERVICE_SCHEMA_BACKFILL_STATISTICS = vol.Schema({
    vol.Required(ATTR_DAYS_TO_FETCH): vol.All(vol.Coerce(int), vol.Range(min=1, max=730)),
    vol.Required(ATTR_FUEL_TYPE): vol.In(["electricity", "gas", "both"]),
    vol.Required(ATTR_FORCE_OVERWRITE, default=False): cv.boolean,
})

SERVICE_SCHEMA_FORCE_UPDATE = vol.Schema({
    vol.Required(ATTR_FUEL_TYPE): vol.In(["electricity", "gas", "both"]),
})


def _resolve_powershout_coordinator(
    hass: HomeAssistant,
    config_entry_id: str | None,
    site_key: str | None,
) -> GenesisEnergyDataUpdateCoordinator:
    """Resolve the coordinator owning a Power Shout property."""
    coordinators = [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, GenesisEnergyDataUpdateCoordinator)
    ]
    if config_entry_id:
        coordinator = hass.data.get(DOMAIN, {}).get(config_entry_id)
        if isinstance(coordinator, GenesisEnergyDataUpdateCoordinator):
            return coordinator
        raise PowerShoutValidationError(
            "The selected Genesis Energy account is unavailable."
        )
    if site_key:
        matches = [
            item for item in coordinators if site_key in item.powershout.states
        ]
        if len(matches) == 1:
            return matches[0]
    if len(coordinators) == 1:
        return coordinators[0]
    raise PowerShoutValidationError(
        "Select a property-specific Genesis Energy account for this Power Shout."
    )


async def _async_cancel_powershout_booking_service(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle a property-safe cancellation of an upcoming Power Shout."""
    try:
        coordinator = _resolve_powershout_coordinator(
            hass,
            call.data.get(ATTR_CONFIG_ENTRY_ID),
            call.data.get(ATTR_SITE_KEY),
        )
        await coordinator.powershout.async_cancel_booking(
            call.data[ATTR_BOOKING_ID],
            call.data.get(ATTR_SITE_KEY),
        )
    except PowerShoutValidationError as err:
        raise ServiceValidationError(str(err)) from err
    except GenesisEnergyError as err:
        raise HomeAssistantError(str(err)) from err

    await coordinator.async_request_refresh()


async def _async_add_powershout_booking_service(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle a property-safe future Power Shout booking."""
    try:
        coordinator = _resolve_powershout_coordinator(
            hass,
            call.data.get(ATTR_CONFIG_ENTRY_ID),
            call.data.get(ATTR_SITE_KEY),
        )
        result = await coordinator.powershout.async_book_future(
            call.data[ATTR_START_DATETIME],
            call.data[ATTR_DURATION_HOURS],
            call.data.get(ATTR_SITE_KEY),
        )
    except PowerShoutValidationError as err:
        raise ServiceValidationError(str(err)) from err
    except GenesisEnergyError as err:
        raise HomeAssistantError(str(err)) from err

    async_create(
        hass,
        f"Your {result['duration_hours']}-hour Power Shout starting at "
        f"{result['start_datetime'].replace('T', ' ')} has been booked.",
        title="Genesis Energy Power Shout Booked",
        notification_id="genesis_powershout_success",
    )
    await coordinator.async_request_refresh()


async def _async_register_lovelace_card(hass: HomeAssistant) -> None:
    """Register the Power Shout card as a Lovelace resource (storage mode only)."""
    www_path = Path(__file__).parent / "www"
    card_path = www_path / _CARD_FILENAME
    if not card_path.is_file():
        LOGGER.warning("Card file not found, skipping Lovelace resource registration: %s", card_path)
        return

    mtime = int(card_path.stat().st_mtime)
    url = f"/{DOMAIN}/{_CARD_FILENAME}?v={mtime}"

    # hass.data["lovelace"] is a dataclass in modern HA, not a dict
    lovelace_data = hass.data.get(lovelace_component.DOMAIN)
    if lovelace_data is None:
        LOGGER.warning("Lovelace not in hass.data — add card resource manually: %s", url)
        return
    resources = getattr(lovelace_data, "resources", None)
    if resources is None:
        LOGGER.info("Lovelace resources not available — add card resource manually: %s", url)
        return

    try:
        items = resources.async_items()
        for item in items:
            item_url = item.get("url", "")
            if _CARD_FILENAME in item_url:
                if item_url != url:
                    # Mtime changed — update the cached-bust URL
                    await resources.async_update_item(item["id"], {"res_type": "module", "url": url})
                    LOGGER.info("Updated Lovelace resource: %s", url)
                return
        await resources.async_create_item({"res_type": "module", "url": url})
        LOGGER.info("Registered Lovelace resource: %s", url)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(
            "Could not register Lovelace resource (%s). Add manually: %s", exc, url
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Genesis Energy from a config entry."""
    LOGGER.info(f"Setting up Genesis Energy for entry: {entry.title}...")

    hass.data.setdefault(DOMAIN, {})
    coordinator = GenesisEnergyDataUpdateCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        LOGGER.error(f"Initial data fetch failed for {entry.title}. Retrying setup.")
        raise
    except Exception as e:
        LOGGER.error(f"Unexpected error during first refresh for {entry.title}: {e}", exc_info=True)
        raise ConfigEntryNotReady(f"Initial data fetch failed with an unexpected error: {e}") from e

    LOGGER.info("Setting up platforms...")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.info("Setting up platforms...✅")

    # ── Lovelace card: serve www/ and register the resource ──────────────────
    global _WWW_PATH_REGISTERED
    if not _WWW_PATH_REGISTERED:
        www_path = Path(__file__).parent / "www"
        if www_path.is_dir():
            await hass.http.async_register_static_paths(
                [StaticPathConfig(f"/{DOMAIN}", str(www_path), cache_headers=False)]
            )
            LOGGER.info("Registered static path /%s → %s", DOMAIN, www_path)
        _WWW_PATH_REGISTERED = True

    @callback
    def _schedule_card_registration(_event=None) -> None:
        hass.async_create_task(_async_register_lovelace_card(hass))

    if hass.is_running:
        _schedule_card_registration()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _schedule_card_registration)
    # ─────────────────────────────────────────────────────────────────────────


    def get_available_services(coordinator: GenesisEnergyDataUpdateCoordinator) -> tuple[bool, bool]:
        """Checks billing plans and returns a tuple of (has_electricity, has_gas)."""
        has_electricity = False
        has_gas = False
        billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
        if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
            for site in billing_plans_data["billingAccountSites"]:
                if isinstance(site.get("supplyPoints"), list):
                    for supply_point in site["supplyPoints"]:
                        if isinstance(supply_point, dict):
                            supply_type = supply_point.get("supplyType")
                            if supply_type == "electricity":
                                has_electricity = True
                            elif supply_type == "naturalGas":
                                has_gas = True
        return has_electricity, has_gas

    if not hass.services.has_service(DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_ADD_POWERSHOUT_BOOKING,
            partial(_async_add_powershout_booking_service, hass),
            schema=SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING,
        )
    
    @callback
    async def async_accept_powershout_offer_service(call: ServiceCall) -> None:
        """Handle the service call to accept a Power Shout offer."""
        offer_id = call.data[ATTR_OFFER_ID]
        LOGGER.info(f"Attempting to accept Power Shout offer with ID: {offer_id}")

        offers_data = coordinator.data.get(DATA_API_POWERSHOUT_OFFERS)
        if not offers_data or not isinstance(offers_data.get("activeOffers"), list):
            LOGGER.error("Could not accept offer: Power Shout offer data is not available.")
            return

        target_offer = None
        for offer in offers_data["activeOffers"]:
            if offer.get("loyaltyOffer", {}).get("guid") == offer_id:
                target_offer = offer
                break
        
        if not target_offer:
            LOGGER.error(f"Could not find an active Power Shout offer with ID: {offer_id}")
            return
            
        try:
            loyalty_account = target_offer['loyaltyAccount']
            loyalty_offer = target_offer['loyaltyOffer']

            success = await coordinator.api.accept_powershout_offer(
                loyalty_account_id=loyalty_account.get('id'),
                member_id=loyalty_account.get('memberGuid'),
                campaign_offer_id=loyalty_offer.get('guid'),
                quantity=loyalty_offer.get('amount'),
                offer_code=target_offer.get('code')
            )

            if success:
                LOGGER.info(f"Successfully accepted Power Shout offer: {target_offer.get('name')}")
                async_create(
                    hass,
                    f"Successfully accepted the '{target_offer.get('name')}' offer! {loyalty_offer.get('amount')} hours have been added to your balance.",
                    title="Genesis Energy Power Shout Offer",
                    notification_id="genesis_powershout_offer_success"
                )
                await coordinator.async_request_refresh()
            else:
                LOGGER.error("Failed to accept Power Shout offer. The API call was unsuccessful.")

        except Exception as e:
            LOGGER.exception(f"An unexpected error occurred while accepting Power Shout offer: {e}")

    hass.services.async_register(
        DOMAIN, SERVICE_ACCEPT_POWERSHOUT_OFFER,
        async_accept_powershout_offer_service,
        schema=SERVICE_SCHEMA_ACCEPT_POWERSHOUT_OFFER,
    )

    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL_POWERSHOUT_BOOKING,
        partial(_async_cancel_powershout_booking_service, hass),
        schema=SERVICE_SCHEMA_CANCEL_POWERSHOUT_BOOKING,
    )

    @callback
    async def async_backfill_statistics_service(call: ServiceCall) -> None:
        """Handle the service call to backfill historical statistics."""
        days = call.data[ATTR_DAYS_TO_FETCH]
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        force_overwrite = call.data[ATTR_FORCE_OVERWRITE]

        has_electricity, has_gas = get_available_services(coordinator)
        
        process_fuel = "none"
        if requested_fuel == "electricity" and has_electricity:
            process_fuel = "electricity"
        elif requested_fuel == "gas" and has_gas:
            process_fuel = "gas"
        elif requested_fuel == "both":
            if has_electricity and has_gas:
                process_fuel = "both"
            elif has_electricity:
                process_fuel = "electricity"
            elif has_gas:
                process_fuel = "gas"
        
        if process_fuel == "none":
            LOGGER.warning(
                "Backfill service called for '%s', but this service is not available on your account. Aborting.❌",
                requested_fuel
            )
            return

        LOGGER.info(f"Backfill service proceeding for '{process_fuel}' for {days} days (Force Overwrite: {force_overwrite})...")
        hass.async_create_task(coordinator.async_backfill_statistics_data(days, process_fuel, force_overwrite))

    hass.services.async_register(
        DOMAIN, SERVICE_BACKFILL_STATISTICS,
        async_backfill_statistics_service,
        schema=SERVICE_SCHEMA_BACKFILL_STATISTICS,
    )

    @callback
    async def async_force_update_service(call: ServiceCall) -> None:
        """Handle the service call to force an update."""
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        LOGGER.info(f"Force update service called (for '{requested_fuel}'). Requesting a full coordinator refresh.")
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE,
        async_force_update_service,
        schema=SERVICE_SCHEMA_FORCE_UPDATE,
    )
    
    def _unload_services():
        hass.services.async_remove(DOMAIN, SERVICE_ACCEPT_POWERSHOUT_OFFER)
        hass.services.async_remove(DOMAIN, SERVICE_CANCEL_POWERSHOUT_BOOKING)
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_STATISTICS)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_UPDATE)
    
    entry.async_on_unload(_unload_services)
    
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    LOGGER.info(f"Genesis Energy setup complete for {entry.data[CONF_EMAIL]} ✅")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            await hass.data[DOMAIN][entry.entry_id].api.close()
            hass.data[DOMAIN].pop(entry.entry_id)
        coordinators = [
            value
            for value in hass.data.get(DOMAIN, {}).values()
            if isinstance(value, GenesisEnergyDataUpdateCoordinator)
        ]
        if not coordinators:
            hass.services.async_remove(DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING)
    return unload_ok

async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry on options update.

    The entry is also updated when token state is persisted to its data; that is a
    data-only write and must not trigger a reload, so only reload when the user-facing
    options actually change.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    new_options = dict(entry.options)
    if coordinator is not None:
        if coordinator.last_options == new_options:
            return
        coordinator.last_options = new_options
    await hass.config_entries.async_reload(entry.entry_id)
