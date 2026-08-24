# custom_components/genesisenergy/coordinator.py
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import asyncio
from typing import Any, Iterable, TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.recorder import get_instance
from homeassistant.util import dt as dt_util


from .api import GenesisEnergyApi
from .exceptions import CannotConnect, InvalidAuth, ApiError
from .const import (
    DOMAIN, LOGGER, DEFAULT_SCAN_INTERVAL_HOURS, CONF_EMAIL, CONF_PASSWORD,
    DEVICE_MANUFACTURER, DEVICE_MODEL, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE,
    DATA_API_POWERSHOUT_INFO, DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS,
    DATA_API_POWERSHOUT_OFFERS, DATA_API_POWERSHOUT_EXPIRING, DATA_API_BILLING_PLANS,
    DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS, DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST,
    DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
    DATA_API_GENERATION_MIX, DATA_API_EV_PLAN_USAGE, DATA_API_ELECTRICITY_FORECAST,
    DATA_API_USAGE_BREAKDOWN, DATA_API_BILLING_SUMMARY, DATA_API_LPG_DETAILS,
    DATA_API_METADATA, DATA_POWERSHOUT_REDEMPTION_STATES,
    RANKED_HOUR_LIMIT, REDEEMED_STORE_VERSION, REDEEMED_KEEP_DAYS,
    CONF_ACCESS_TOKEN, CONF_ACCESS_TOKEN_EXPIRY, CONF_REFRESH_TOKEN, CONF_REFRESH_TOKEN_EXPIRY
)
from .powershout import NZ_TIME_ZONE, PowerShoutRedemption, build_ranked_hours
from .hourly_costs import HourlyCostSource

if TYPE_CHECKING:
    from .sensor import GenesisEnergyStatisticsSensor


class GenesisEnergyDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: ConfigEntry
    api: GenesisEnergyApi
    device_info: DeviceInfo

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        # Snapshot options so token persistence (a data-only write) doesn't trigger a reload.
        self.last_options = dict(entry.options)
        token_state = {
            "access_token": entry.data.get(CONF_ACCESS_TOKEN),
            "access_token_expiry": entry.data.get(CONF_ACCESS_TOKEN_EXPIRY),
            "refresh_token": entry.data.get(CONF_REFRESH_TOKEN),
            "refresh_token_expiry": entry.data.get(CONF_REFRESH_TOKEN_EXPIRY),
        }
        self.api = GenesisEnergyApi(
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            token_state=token_state,
            token_update_cb=self._persist_token_state,
        )
        self.powershout = PowerShoutRedemption(self.api)
        self.hour_costs = HourlyCostSource(hass, self.api)
        # Genesis omits retrospective redemptions from its bookings list and keeps
        # recommending them, so remember what was redeemed here.
        self._redeemed_store: Store = Store(
            hass, REDEEMED_STORE_VERSION, f"{DOMAIN}_redeemed_hours_{entry.entry_id}"
        )
        self._redeemed_hours: set[str] | None = None
        device_name = self.config_entry.title
        self.device_info = DeviceInfo(identifiers={(DOMAIN, self.config_entry.entry_id)}, name=device_name, manufacturer=DEVICE_MANUFACTURER, model=f"{DEVICE_MODEL} (Polls every {DEFAULT_SCAN_INTERVAL_HOURS}h)", configuration_url="https://myaccount.genesisenergy.co.nz/")
        self.statistics_sensors: list["GenesisEnergyStatisticsSensor"] = []
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=timedelta(hours=DEFAULT_SCAN_INTERVAL_HOURS))
    
    def _persist_token_state(self, state: dict) -> None:
        """Persist token state to the config entry so restarts skip the scrape login."""
        new_data = {
            **self.config_entry.data,
            CONF_ACCESS_TOKEN: state.get("access_token"),
            CONF_ACCESS_TOKEN_EXPIRY: state.get("access_token_expiry"),
            CONF_REFRESH_TOKEN: state.get("refresh_token"),
            CONF_REFRESH_TOKEN_EXPIRY: state.get("refresh_token_expiry"),
        }
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # Authenticate up front (outside the per-call gather, which swallows errors)
            # so a credential failure can trigger HA's reauth flow.
            await self.api.async_login()
            return await self._async_fetch_all_data()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except (CannotConnect, ApiError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error updating data: {err}") from err

    async def _async_fetch_all_data(self) -> dict[str, Any]:
        """Fetch all data from the API in parallel."""
        days_for_regular_fetch = 4
        
        api_calls = {
            DATA_API_BILLING_PLANS: self.api.get_billing_plans(),
            DATA_API_BILLING_SUMMARY: self.api.get_billing_summary(),
            DATA_API_ELECTRICITY_USAGE: self.api.get_energy_data(days_for_regular_fetch),
            DATA_API_EV_PLAN_USAGE: self.api.get_ev_plan_usage(),
            DATA_API_GAS_USAGE: self.api.get_gas_data(days_for_regular_fetch),
            DATA_API_POWERSHOUT_INFO: self.api.get_powershout_info(),
            DATA_API_POWERSHOUT_BALANCE: self.api.get_powershout_balance(),
            DATA_API_POWERSHOUT_BOOKINGS: self.api.get_powershout_bookings(),
            DATA_API_POWERSHOUT_OFFERS: self.api.get_powershout_offers(),
            DATA_API_POWERSHOUT_EXPIRING: self.api.get_powershout_expiring_hours(),
            DATA_API_METADATA: self.api.get_initialize_metadata(),
            DATA_API_WIDGET_HERO: self.api.get_widget_hero_info(),
            DATA_API_WIDGET_BILLS: self.api.get_widget_bill_summary(),
            DATA_API_WIDGET_PROPERTY_LIST: self.api.get_widget_property_list(),
            DATA_API_WIDGET_PROPERTY_SWITCHER: self.api.get_widget_property_switcher(),
            DATA_API_WIDGET_SIDEKICK: self.api.get_widget_sidekick(),
            DATA_API_WIDGET_DASHBOARD_POWERSHOUT: self.api.get_widget_dashboard_powershout(),
            DATA_API_WIDGET_ECO_TRACKER: self.api.get_widget_eco_tracker(),
            DATA_API_WIDGET_DASHBOARD_LIST: self.api.get_widget_dashboard_list(),
            DATA_API_WIDGET_ACTION_TILE_LIST: self.api.get_widget_action_tile_list(),
            DATA_API_NEXT_BEST_ACTION: self.api.get_next_best_action(),
            DATA_API_GENERATION_MIX: self.api.get_generation_mix(),
            DATA_API_ELECTRICITY_FORECAST: self.api.get_electricity_forecast(),
            DATA_API_USAGE_BREAKDOWN: self.api.get_usage_breakdown(),
        }
        
        results = await asyncio.gather(*api_calls.values(), return_exceptions=True)
        
        fetched_data = {}
        for key, result in zip(api_calls.keys(), results):
            if isinstance(result, Exception):
                LOGGER.info("Could not fetch data for %s. This may be expected. Error: %s", key, result)
                fetched_data[key] = None
            else:
                fetched_data[key] = result

        lpg_details = {}
        try:
            order_status = await self.api.get_lpg_order_status()
            if order_status and isinstance(order_status.get("billingAccountSites"), list):
                lpg_supply_points = [sp for site in order_status.get("billingAccountSites", []) for sp in site.get("supplyPoints", []) if sp.get("supplyAgreementId")]
                sa_ids = [sp["supplyAgreementId"] for sp in lpg_supply_points]
                
                if sa_ids:
                    history_results, summary_results = await asyncio.gather(
                        asyncio.gather(*[self.api.get_lpg_delivery_history(sa_id) for sa_id in sa_ids], return_exceptions=True),
                        asyncio.gather(*[self.api.get_lpg_delivery_summary(sa_id) for sa_id in sa_ids], return_exceptions=True)
                    )
                    histories_by_sa_id = {sa_id: res for sa_id, res in zip(sa_ids, history_results) if not isinstance(res, Exception)}
                    summaries_by_sa_id = {sa_id: res for sa_id, res in zip(sa_ids, summary_results) if not isinstance(res, Exception)}

                    for sp_data in lpg_supply_points:
                        sp_id = sp_data["id"]
                        sa_id = sp_data["supplyAgreementId"]
                        lpg_details[sp_id] = {
                            "order_status": sp_data,
                            "delivery_history": histories_by_sa_id.get(sa_id),
                            "delivery_summary": summaries_by_sa_id.get(sa_id)
                        }

        except Exception as err:
            if "supplyAgreementIds" in str(err):
                LOGGER.debug("Skipping LPG fetch — account has no LPG supply agreements.")
            else:
                LOGGER.warning("An error occurred during LPG data fetching: %s", err)

        fetched_data[DATA_API_LPG_DETAILS] = lpg_details
        if lpg_details:
            LOGGER.debug("Final processed LPG details payload: %s", lpg_details)
        else:
            LOGGER.debug("No LPG details to process (likely no LPG on account).")

        try:
            fetched_data[DATA_POWERSHOUT_REDEMPTION_STATES] = (
                await self.powershout.async_load_states(
                    fetched_data.get(DATA_API_METADATA),
                    fetched_data.get(DATA_API_POWERSHOUT_INFO),
                )
            )
        except Exception as err:
            LOGGER.warning("Could not load retrospective Power Shout data: %s", err)
            fetched_data[DATA_POWERSHOUT_REDEMPTION_STATES] = {}

        try:
            fetched_data[DATA_POWERSHOUT_REDEMPTION_STATES] = await self._async_rank_past_hours(
                fetched_data.get(DATA_POWERSHOUT_REDEMPTION_STATES) or {},
                fetched_data.get(DATA_API_POWERSHOUT_BOOKINGS),
            )
        except Exception as err:
            LOGGER.warning("Could not rank past Power Shout hours: %s", err)

        return fetched_data

    async def _async_redeemed_hours(self) -> set[str]:
        """Return past hours redeemed through this integration."""
        if self._redeemed_hours is None:
            stored = await self._redeemed_store.async_load()
            hours = stored.get("hours") if isinstance(stored, dict) else None
            self._redeemed_hours = set(hours) if isinstance(hours, list) else set()
        return self._redeemed_hours

    async def async_record_redeemed(self, starts: Iterable[str]) -> None:
        """Record redeemed past hours so they leave the ranked list immediately."""
        hours = await self._async_redeemed_hours()
        added = {str(value) for value in starts if value}
        if added <= hours:
            return
        hours |= added
        cutoff = (
            datetime.now(NZ_TIME_ZONE).date() - timedelta(days=REDEEMED_KEEP_DAYS)
        ).isoformat()
        self._redeemed_hours = {value for value in hours if value[:10] >= cutoff}
        await self._redeemed_store.async_save(
            {"hours": sorted(self._redeemed_hours)}
        )

    def _booked_hour_starts(self, bookings_data: Any) -> frozenset[str]:
        """Return local hours already covered by a Power Shout booking."""
        if not isinstance(bookings_data, dict):
            return frozenset()
        bookings = bookings_data.get("bookings")
        if not isinstance(bookings, list):
            return frozenset()

        starts: set[str] = set()
        for booking in bookings:
            if not isinstance(booking, dict) or not booking.get("startDateTime"):
                continue
            try:
                start = datetime.fromisoformat(str(booking["startDateTime"]))
            except (TypeError, ValueError):
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=NZ_TIME_ZONE)
            start = start.astimezone(NZ_TIME_ZONE).replace(
                minute=0, second=0, microsecond=0, tzinfo=None
            )
            try:
                duration = max(1, int(float(booking.get("duration") or 1)))
            except (TypeError, ValueError):
                duration = 1
            for offset in range(duration):
                starts.add(
                    (start + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%S")
                )
        return frozenset(starts)

    async def _async_rank_past_hours(
        self, states: dict[str, Any], bookings_data: Any
    ) -> dict[str, Any]:
        """Attach cost-ranked eligible hours to each retrospective property state."""
        # Ranking runs off local statistics, so it still works when Genesis'
        # own recommendation call is down.
        windows = {
            state.past_days
            for state in states.values()
            if getattr(state, "past_days", 0) > 0
        }
        if not windows:
            return states

        today = datetime.now(NZ_TIME_ZONE).date()
        latest = today - timedelta(days=1)
        earliest = today - timedelta(days=max(windows))
        hours = await self.hour_costs.async_hour_costs(earliest, latest)
        if not hours:
            return states

        booked = self._booked_hour_starts(bookings_data) | await self._async_redeemed_hours()
        ranked_states: dict[str, Any] = {}
        for site_key, state in states.items():
            if getattr(state, "past_days", 0) <= 0:
                ranked_states[site_key] = state
                continue
            site_earliest = (today - timedelta(days=state.past_days)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            in_window = {
                key: value for key, value in hours.items() if key >= site_earliest
            }
            ranked_states[site_key] = replace(
                state,
                ranked_hours=build_ranked_hours(
                    in_window, state.recommendations, booked, RANKED_HOUR_LIMIT
                ),
            )
        return ranked_states

    async def async_backfill_statistics_data(self, days_to_fetch: int, fuel_type: str, force_overwrite: bool = False) -> None:
        """
        Service to backfill historical statistics, intelligently fetching only missing days.
        """
        from .sensor import GenesisEnergyStatisticsSensor
        LOGGER.info(f"Starting historical backfill for '{fuel_type}' for the last {days_to_fetch} days...")
        
        process_elec, process_gas = "electricity" in [fuel_type, "both"], "gas" in [fuel_type, "both"]

        elec_sensor: GenesisEnergyStatisticsSensor | None = None
        gas_sensor: GenesisEnergyStatisticsSensor | None = None
        for sensor in self.statistics_sensors:
            if sensor._fuel_type == "Electricity":
                elec_sensor = sensor
            elif sensor._fuel_type == "Gas":
                gas_sensor = sensor
        
        LOGGER.info(f"Coordinator statistics_sensors currently: {self.statistics_sensors}")
        LOGGER.info(f"Detected Elec Sensor: {elec_sensor is not None}, Gas Sensor: {gas_sensor is not None}")

        async def _backfill_fuel(sensor: GenesisEnergyStatisticsSensor, is_elec: bool):
            """Core logic to find missing days and fetch data for a single fuel type."""
            fuel_name = "Electricity" if is_elec else "Gas"
            LOGGER.info(f"{fuel_name} backfill starting...")

            today = dt_util.now().date()
            start_date = today - timedelta(days=days_to_fetch - 1)
            all_desired_dates = {start_date + timedelta(days=x) for x in range(days_to_fetch)}
            
            dates_to_fetch = []
            
            if force_overwrite:
                LOGGER.debug(f"[{fuel_name}] Force overwrite is enabled. Will fetch for all days in the period.")
                dates_to_fetch = sorted(list(all_desired_dates))
            else:
                start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
                existing_stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass, start_datetime, None, {sensor._consumption_statistic_id},
                    "day", None, {"sum"},
                )
                existing_dates = set()
                if sensor._consumption_statistic_id in existing_stats:
                    for stat in existing_stats[sensor._consumption_statistic_id]:
                        stat_date = datetime.fromtimestamp(stat['start'], tz=timezone.utc).date()
                        existing_dates.add(stat_date)

                LOGGER.info(f"[{fuel_name}] Found {len(existing_dates)} days with existing statistics in the last {days_to_fetch} days.")
                dates_to_fetch = sorted(list(all_desired_dates - existing_dates))

            if today in dates_to_fetch:
                LOGGER.debug(f"[{fuel_name}] Removing today ({today}) from the fetch list as its data is not yet final.")
                dates_to_fetch.remove(today)

            if not dates_to_fetch:
                LOGGER.info(f"[{fuel_name}] No missing past days found to backfill.")
                return

            all_fetched_data = []
            api_call = self.api.get_energy_data_for_period if is_elec else self.api.get_gas_data_for_period
            
            chunk_size = 4
            date_chunks = [dates_to_fetch[i:i + chunk_size] for i in range(0, len(dates_to_fetch), chunk_size)]

            for chunk in date_chunks:
                chunk_start_date = chunk[0].strftime("%Y-%m-%d")
                chunk_end_date = chunk[-1].strftime("%Y-%m-%d")
                LOGGER.info(f"  Fetching {fuel_name} chunk: {chunk_start_date} to {chunk_end_date}")
                try:
                    res = await api_call(chunk_start_date, chunk_end_date)
                    if res and 'usage' in res:
                        all_fetched_data.extend(res['usage'])
                    await asyncio.sleep(1) 
                except Exception as e:
                    LOGGER.error(f"Error fetching backfill chunk for {chunk_start_date} to {chunk_end_date}. Skipping this chunk. Error: {e}")

            if all_fetched_data:
                await sensor.async_process_statistics_data(all_fetched_data, force_overwrite, start_date=start_date)
            else:
                LOGGER.warning(f"[{fuel_name}] Attempted to fetch data but received no data from the API.")

        if process_elec and elec_sensor:
            await _backfill_fuel(elec_sensor, is_elec=True)
        if process_gas and gas_sensor:
            await _backfill_fuel(gas_sensor, is_elec=False)

        LOGGER.info(f"Historical backfill complete for '{fuel_type}' ✅")
