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

_LOGGER = logging.getLogger(__name__)

CONF_STATION_ID = "station_id"
CONF_STATION_TYPE = "type"

DOMAIN = "noaa_tides"

DEFAULT_NAME = "NOAA Tides"

STATION_TYPES = ["tides", "temp", "buoy"]


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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Set unique_id based on station_id and type to prevent duplicates
                await self.async_set_unique_id(
                    f"{user_input[CONF_STATION_ID]}_{user_input[CONF_STATION_TYPE]}"
                )
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=info["title"], data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): str,
                vol.Required(CONF_STATION_TYPE): vol.In(STATION_TYPES),
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
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
