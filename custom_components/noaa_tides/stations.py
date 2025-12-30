"""NOAA and NDBC station metadata management."""
from __future__ import annotations

import logging
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

# NOAA Tides and Currents Metadata API
NOAA_STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"

# Cache for station data to avoid repeated API calls
_station_cache: dict[str, Any] = {}


async def fetch_noaa_stations(hass, station_type: str = "tidepredictions") -> list[dict[str, Any]]:
    """Fetch station metadata from NOAA API.
    
    Args:
        hass: Home Assistant instance
        station_type: Type of stations to fetch (tidepredictions, waterlevels, etc.)
    
    Returns:
        List of station dictionaries with id, name, state, etc.
    """
    cache_key = f"noaa_{station_type}"
    
    if cache_key in _station_cache:
        return _station_cache[cache_key]
    
    try:
        response = await hass.async_add_executor_job(
            lambda: requests.get(
                NOAA_STATIONS_URL,
                params={"type": station_type},
                timeout=10
            )
        )
        
        if response.status_code == 200:
            data = response.json()
            stations = data.get("stations", [])
            _station_cache[cache_key] = stations
            return stations
        else:
            _LOGGER.error("Failed to fetch NOAA stations: HTTP %s", response.status_code)
            return []
    except Exception as err:
        _LOGGER.error("Error fetching NOAA stations: %s", err)
        return []


def get_states_from_stations(stations: list[dict[str, Any]]) -> list[str]:
    """Extract unique states from station list, sorted alphabetically.
    
    Args:
        stations: List of station dictionaries
    
    Returns:
        Sorted list of unique state names
    """
    states = set()
    for station in stations:
        state = station.get("state")
        if state:
            states.add(state)
    return sorted(states)


def filter_stations_by_state(stations: list[dict[str, Any]], state: str) -> list[dict[str, Any]]:
    """Filter stations by state.
    
    Args:
        stations: List of station dictionaries
        state: State to filter by
    
    Returns:
        List of stations in the specified state
    """
    return [s for s in stations if s.get("state") == state]


def get_station_options(stations: list[dict[str, Any]]) -> dict[str, str]:
    """Convert station list to options dict for selector.
    
    Args:
        stations: List of station dictionaries
    
    Returns:
        Dict mapping station_id to display name (name - id)
    """
    options = {}
    for station in stations:
        station_id = station.get("id")
        station_name = station.get("name", "Unknown")
        if station_id:
            options[station_id] = f"{station_name} ({station_id})"
    return options


async def verify_station_id(hass, station_id: str, station_type: str) -> tuple[bool, str]:
    """Verify if a station ID exists and is valid.
    
    Args:
        hass: Home Assistant instance
        station_id: Station ID to verify
        station_type: Type of station (tides, temp, buoy)
    
    Returns:
        Tuple of (is_valid, station_name or error_message)
    """
    if station_type == "buoy":
        # For buoy, we'll do a simpler validation
        # NDBC buoy IDs are typically 5 characters (alphanumeric)
        # Common formats: 5-digit numbers (e.g., 44017) or 5-char alphanumeric (e.g., 41001)
        if len(station_id) >= 5 and station_id.isalnum():
            return True, f"Buoy {station_id}"
        else:
            return False, "Invalid buoy ID format (must be at least 5 alphanumeric characters)"
    
    # For NOAA stations (tides/temp), fetch and check
    try:
        # First check our cache
        stations = await fetch_noaa_stations(hass, "tidepredictions")
        
        # Look for exact match
        for station in stations:
            if station.get("id") == station_id:
                station_name = station.get("name", "Unknown Station")
                return True, station_name
        
        # If not found in tide predictions, also check water levels
        stations = await fetch_noaa_stations(hass, "waterlevels")
        for station in stations:
            if station.get("id") == station_id:
                station_name = station.get("name", "Unknown Station")
                return True, station_name
        
        return False, f"Station ID {station_id} not found"
    except Exception as err:
        _LOGGER.error("Error verifying station: %s", err)
        return False, str(err)
