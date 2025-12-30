"""The noaa_tides component."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import METRIC_SYSTEM

_LOGGER = logging.getLogger(__name__)

DOMAIN = "noaa_tides"
PLATFORMS = [Platform.SENSOR]

CONF_STATION_ID = "station_id"
CONF_STATION_TYPE = "type"

DEFAULT_TIMEZONE = "lst_ldt"
UNIT_SYSTEMS = ["english", "metric"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NOAA Tides from a config entry."""
    from .sensor import (
        NOAATidesDataUpdateCoordinator,
        NOAATemperatureDataUpdateCoordinator,
        NOAABuoyDataUpdateCoordinator,
    )

    hass.data.setdefault(DOMAIN, {})
    
    # Get configuration
    station_id = entry.data[CONF_STATION_ID]
    station_type = entry.data[CONF_STATION_TYPE]
    
    # Determine unit system and timezone from Home Assistant config
    timezone = DEFAULT_TIMEZONE
    if hass.config.units is METRIC_SYSTEM:
        unit_system = UNIT_SYSTEMS[1]  # "metric"
    else:
        unit_system = UNIT_SYSTEMS[0]  # "english"
    
    # Create appropriate coordinator based on station type
    if station_type == "tides":
        coordinator = NOAATidesDataUpdateCoordinator(
            hass, station_id, timezone, unit_system
        )
    elif station_type == "temp":
        coordinator = NOAATemperatureDataUpdateCoordinator(
            hass, station_id, timezone, unit_system
        )
    else:  # buoy
        coordinator = NOAABuoyDataUpdateCoordinator(
            hass, station_id, timezone, unit_system
        )
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()
    
    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
