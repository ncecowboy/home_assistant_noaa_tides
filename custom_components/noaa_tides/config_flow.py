"""Config flow for NOAA Tides integration."""
from __future__ import annotations

import logging
from typing import Any

import noaa_coops as nc
import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv

from .stations import (
    fetch_noaa_stations,
    get_states_from_stations,
    filter_stations_by_state,
    get_station_options,
    verify_station_id,
)

_LOGGER = logging.getLogger(__name__)

CONF_STATION_ID = "station_id"
CONF_STATION_TYPE = "type"
CONF_STATE = "state"
CONF_ENTRY_METHOD = "entry_method"

DOMAIN = "noaa_tides"

DEFAULT_NAME = "NOAA Tides"

STATION_TYPES = ["tides", "temp", "buoy"]
ENTRY_METHODS = ["lookup", "manual"]


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    station_id = data[CONF_STATION_ID]
    station_type = data[CONF_STATION_TYPE]

    # For tides and temp types, validate station exists via noaa_coops
    if station_type in ["tides", "temp"]:
        try:
            await hass.async_add_executor_job(nc.Station, station_id)
        except (ValueError, requests.exceptions.ConnectionError) as err:
            _LOGGER.error(f"Failed to validate station {station_id}: {err}")
            raise ValueError("cannot_connect")
    # For buoy type, just ensure the station_id is provided
    # API validation happens at runtime since buoy API can be slow

    # Return info that you want to store in the config entry.
    return {"title": data.get(CONF_NAME, f"{DEFAULT_NAME} {station_id}")}


class NOAATidesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NOAA Tides."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.config_data: dict[str, Any] = {}
        self.stations_cache: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - choose station type and entry method."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.config_data[CONF_STATION_TYPE] = user_input[CONF_STATION_TYPE]
            self.config_data[CONF_ENTRY_METHOD] = user_input[CONF_ENTRY_METHOD]
            
            # For buoy type or manual entry, go directly to manual entry
            if user_input[CONF_STATION_TYPE] == "buoy" or user_input[CONF_ENTRY_METHOD] == "manual":
                return await self.async_step_manual()
            else:
                # For tides/temp with lookup, go to state selection
                return await self.async_step_state()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_STATION_TYPE, default="tides"): vol.In(STATION_TYPES),
                vol.Required(CONF_ENTRY_METHOD, default="lookup"): vol.In(ENTRY_METHODS),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    async def async_step_state(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle state selection step."""
        errors: dict[str, str] = {}

        # Fetch stations if not already cached
        if not self.stations_cache:
            station_type = self.config_data[CONF_STATION_TYPE]
            api_type = "tidepredictions" if station_type == "tides" else "waterlevels"
            self.stations_cache = await fetch_noaa_stations(self.hass, api_type)
            
            if not self.stations_cache:
                # If we can't fetch stations, fall back to manual entry
                _LOGGER.warning("Could not fetch station list, falling back to manual entry")
                return await self.async_step_manual()

        if user_input is not None:
            self.config_data[CONF_STATE] = user_input[CONF_STATE]
            return await self.async_step_station()

        # Get list of states
        states = get_states_from_stations(self.stations_cache)
        
        if not states:
            # No states found, fall back to manual entry
            return await self.async_step_manual()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_STATE): vol.In(states),
            }
        )

        return self.async_show_form(
            step_id="state", data_schema=data_schema, errors=errors
        )

    async def async_step_station(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle station selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.config_data[CONF_STATION_ID] = user_input[CONF_STATION_ID]
            return await self.async_step_name()

        # Filter stations by selected state
        state = self.config_data[CONF_STATE]
        filtered_stations = filter_stations_by_state(self.stations_cache, state)
        
        if not filtered_stations:
            errors["base"] = "no_stations_in_state"
            return await self.async_step_manual()

        # Get station options
        station_options = get_station_options(filtered_stations)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): vol.In(station_options),
            }
        )

        return self.async_show_form(
            step_id="station", data_schema=data_schema, errors=errors
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual station ID entry with instant verification."""
        errors: dict[str, str] = {}

        if user_input is not None:
            station_id = user_input[CONF_STATION_ID]
            station_type = self.config_data[CONF_STATION_TYPE]
            
            # Verify the station ID instantly
            is_valid, message = await verify_station_id(self.hass, station_id, station_type)
            
            if not is_valid:
                errors["base"] = "invalid_station_id"
                _LOGGER.warning("Station validation failed: %s", message)
            else:
                self.config_data[CONF_STATION_ID] = station_id
                return await self.async_step_name()

        data_schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): str,
            }
        )

        return self.async_show_form(
            step_id="manual", data_schema=data_schema, errors=errors
        )

    async def async_step_name(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle name entry step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.config_data[CONF_NAME] = user_input.get(CONF_NAME, DEFAULT_NAME)
            
            # Final validation
            try:
                info = await validate_input(self.hass, self.config_data)
            except ValueError:
                errors["base"] = "cannot_connect"
                return self.async_show_form(
                    step_id="name", 
                    data_schema=vol.Schema({
                        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    }),
                    errors=errors
                )
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
                return self.async_show_form(
                    step_id="name", 
                    data_schema=vol.Schema({
                        vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                    }),
                    errors=errors
                )

            # Set unique_id based on station_id and type to prevent duplicates
            await self.async_set_unique_id(
                f"{self.config_data[CONF_STATION_ID]}_{self.config_data[CONF_STATION_TYPE]}"
            )
            self._abort_if_unique_id_configured()

            # Clean up temporary fields before creating entry
            final_data = {
                CONF_STATION_ID: self.config_data[CONF_STATION_ID],
                CONF_STATION_TYPE: self.config_data[CONF_STATION_TYPE],
                CONF_NAME: self.config_data[CONF_NAME],
            }

            return self.async_create_entry(title=info["title"], data=final_data)

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )

        return self.async_show_form(
            step_id="name", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NOAATidesOptionsFlowHandler:
        """Get the options flow for this handler."""
        return NOAATidesOptionsFlowHandler(config_entry)


class NOAATidesOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for NOAA Tides."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        # No options to configure - timezone and unit system come from Home Assistant
        return self.async_abort(reason="no_options")
