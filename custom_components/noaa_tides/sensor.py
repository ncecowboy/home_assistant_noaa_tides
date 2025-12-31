"""Support for the NOAA Tides and Currents API."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as tz
import logging
import requests
import math
from typing import Any, Optional

import noaa_coops as nc
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    CONF_NAME,
    CONF_TIME_ZONE,
    CONF_UNIT_SYSTEM,
    UnitOfLength,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util.unit_system import METRIC_SYSTEM
from homeassistant.components.sensor import SensorDeviceClass

_LOGGER = logging.getLogger(__name__)

DOMAIN = "noaa_tides"

CONF_STATION_ID = "station_id"
CONF_STATION_TYPE = "type"

DEFAULT_ATTRIBUTION = "Data provided by NOAA"
BUOY_ATTRIBUTION = "Data provided by NDBC"
DEFAULT_NAME = "NOAA Tides"
DEFAULT_TIMEZONE = "lst_ldt"

# Time window for fetching current water level observations (in hours)
WATER_LEVEL_LOOKBACK_HOURS = 1

TIMEZONES = ["gmt", "lst", "lst_ldt"]
UNIT_SYSTEMS = ["english", "metric"]
STATION_TYPES = ["tides", "temp", "buoy"]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_STATION_ID): cv.string,
        vol.Required(CONF_STATION_TYPE): vol.In(STATION_TYPES),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_TIME_ZONE, default=DEFAULT_TIMEZONE): vol.In(TIMEZONES),
        vol.Optional(CONF_UNIT_SYSTEM): vol.In(UNIT_SYSTEMS)
    }
)


class NOAATidesDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching NOAA Tides data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        timezone: str,
        unit_system: str,
    ) -> None:
        """Initialize the coordinator."""
        self.station_id = station_id
        self.timezone = timezone
        self.unit_system = unit_system
        self.station: nc.Station | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"NOAA Tides {station_id}",
            update_interval=timedelta(hours=1),
        )

    async def _async_update_data(self) -> Any:
        """Fetch data from NOAA Tides API."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except (ValueError, requests.exceptions.ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def _fetch_data(self) -> dict[str, Any]:
        """Fetch the tide predictions data and current water level."""
        if self.station is None:
            _LOGGER.debug("No station object exists yet- creating one.")
            self.station = nc.Station(self.station_id)

        begin = datetime.now() - timedelta(hours=24)
        begin_date = begin.strftime("%Y%m%d %H:%M")
        end = begin + timedelta(hours=48)
        end_date = end.strftime("%Y%m%d %H:%M")

        df_predictions = self.station.get_data(
            begin_date=begin_date,
            end_date=end_date,
            product="predictions",
            datum="MLLW",
            interval="hilo",
            units=self.unit_system,
            time_zone=self.timezone,
        )

        _LOGGER.debug("Tide data queried with start time set to %s", begin_date)
        
        # Fetch current water level data
        current_water_level = None
        try:
            current_end = datetime.now()
            current_begin = current_end - timedelta(hours=WATER_LEVEL_LOOKBACK_HOURS)
            df_water_level = self.station.get_data(
                begin_date=current_begin.strftime("%Y%m%d %H:%M"),
                end_date=current_end.strftime("%Y%m%d %H:%M"),
                product="water_level",
                datum="MLLW",
                units=self.unit_system,
                time_zone=self.timezone,
            )
            current_water_level = df_water_level
            _LOGGER.debug(
                "Current water level data retrieved: %d records",
                len(df_water_level) if df_water_level is not None else 0,
            )
        except ValueError as err:
            _LOGGER.debug("Could not fetch current water level data: %s", err.args)
        except requests.exceptions.ConnectionError as err:
            _LOGGER.debug("Couldn't connect to NOAA Tides and Currents API for water level: %s", err)
        
        return {
            "predictions": df_predictions,
            "current_water_level": current_water_level,
        }


class NOAATemperatureDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching NOAA Temperature data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        timezone: str,
        unit_system: str,
    ) -> None:
        """Initialize the coordinator."""
        self.station_id = station_id
        self.timezone = timezone
        self.unit_system = unit_system
        self.station: nc.Station | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"NOAA Temperature {station_id}",
            update_interval=timedelta(minutes=30),
        )

    async def _async_update_data(self) -> Any:
        """Fetch data from NOAA Temperature API."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except (ValueError, requests.exceptions.ConnectionError) as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def _fetch_data(self) -> tuple[Any, Any]:
        """Fetch the temperature data."""
        if self.station is None:
            _LOGGER.debug("No station object exists yet- creating one.")
            self.station = nc.Station(self.station_id)

        end = datetime.now()
        delta = timedelta(minutes=60)
        begin = end - delta
        temps = None
        air_temps = None

        try:
            temps = self.station.get_data(
                begin_date=begin.strftime("%Y%m%d %H:%M"),
                end_date=end.strftime("%Y%m%d %H:%M"),
                product="water_temperature",
                units=self.unit_system,
                time_zone=self.timezone,
            ).tail(1)
            _LOGGER.debug(
                "Recent water temperature data queried with start time set to %s",
                begin.strftime("%m-%d-%Y %H:%M"),
            )
        except ValueError as err:
            _LOGGER.error("Check NOAA Tides and Currents: %s", err.args)

        try:
            air_temps = self.station.get_data(
                begin_date=begin.strftime("%Y%m%d %H:%M"),
                end_date=end.strftime("%Y%m%d %H:%M"),
                product="air_temperature",
                units=self.unit_system,
                time_zone=self.timezone,
            ).tail(1)
            _LOGGER.debug(
                "Recent temperature data queried with start time set to %s",
                begin.strftime("%m-%d-%Y %H:%M"),
            )
        except ValueError as err:
            _LOGGER.error("Check NOAA Tides and Currents: %s", err.args)

        return (temps, air_temps)


class NOAABuoyDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching NOAA Buoy data from the API."""

    FMT_URI = "https://www.ndbc.noaa.gov/data/realtime2/%s.txt"

    def __init__(
        self,
        hass: HomeAssistant,
        station_id: str,
        timezone: str,
        unit_system: str,
    ) -> None:
        """Initialize the coordinator."""
        self.station_id = station_id
        self.station_url = self.FMT_URI % station_id
        self.timezone = timezone
        self.unit_system = unit_system

        super().__init__(
            hass,
            _LOGGER,
            name=f"NOAA Buoy {station_id}",
            update_interval=timedelta(minutes=30),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from NOAA Buoy API."""
        try:
            return await self.hass.async_add_executor_job(self._fetch_data)
        except requests.exceptions.RequestException as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def _fetch_data(self) -> dict[str, Any]:
        """Fetch the buoy data."""
        _LOGGER.debug("Querying the buoy database")
        r = requests.get(self.station_url, timeout=10)
        r.raise_for_status()

        lines = r.text.splitlines()
        if len(lines) < 3:
            _LOGGER.debug("Buoy response text: %s", r.text)
            raise UpdateFailed(f"Received fewer than 3 lines of data from buoy {self.station_id}")

        data = {}
        head = '\n    '.join(lines[0:3])
        _LOGGER.debug("Buoy data head:\n    %s", head)
        fields = lines[0].strip("#").split()
        units = lines[1].strip("#").split()
        values = lines[2].split()  # latest values are at the top of the file

        for i in range(len(fields)):
            if values[i] == "MM":
                data[fields[i]] = (units[i], values[i])
            elif "." in values[i]:
                data[fields[i]] = (units[i], float(values[i]))
            else:
                data[fields[i]] = (units[i], int(values[i]))

        return data


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NOAA Tides sensor from a config entry."""
    # Get coordinator from hass.data (stored in __init__.py)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    station_id = entry.data[CONF_STATION_ID]
    station_type = entry.data[CONF_STATION_TYPE]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)
    
    # Determine unit system from Home Assistant config
    if hass.config.units is METRIC_SYSTEM:
        unit_system = UNIT_SYSTEMS[1]  # "metric"
    else:
        unit_system = UNIT_SYSTEMS[0]  # "english"

    # Create appropriate sensor(s) based on station type
    sensors = []
    if station_type == "tides":
        # Create tides sensor
        sensors.append(NOAATidesAndCurrentsSensor(
            coordinator, entry.entry_id, name, station_id, unit_system
        ))
        # Create current water level sensor
        sensors.append(NOAACurrentWaterLevelSensor(
            coordinator, entry.entry_id, name, station_id, unit_system
        ))
    elif station_type == "temp":
        sensors.append(NOAATemperatureSensor(
            coordinator, entry.entry_id, name, station_id, unit_system
        ))
    else:  # buoy
        sensors.append(NOAABuoySensor(
            coordinator, entry.entry_id, name, station_id, unit_system
        ))

    async_add_entities(sensors, True)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the NOAA Tides and Currents sensor (legacy YAML config)."""
    station_id = config[CONF_STATION_ID]
    station_type = config[CONF_STATION_TYPE]
    name = config.get(CONF_NAME, DEFAULT_NAME)
    
    # For YAML config, default to lst_ldt if not specified
    # (UI config always uses system settings)
    timezone = config.get(CONF_TIME_ZONE, DEFAULT_TIMEZONE)

    # For YAML config, fall back to system settings if not specified
    if CONF_UNIT_SYSTEM in config:
        unit_system = config[CONF_UNIT_SYSTEM]
    elif hass.config.units is METRIC_SYSTEM:
        unit_system = UNIT_SYSTEMS[1]
    else:
        unit_system = UNIT_SYSTEMS[0]

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
    
    # Create sensor(s) with coordinator
    # For YAML config, use station_id as entry_id since there's no config entry
    entry_id = f"yaml_{station_id}_{station_type}"
    
    sensors = []
    if station_type == "tides":
        # Create tides sensor
        sensors.append(NOAATidesAndCurrentsSensor(
            coordinator, entry_id, name, station_id, unit_system
        ))
        # Create current water level sensor
        sensors.append(NOAACurrentWaterLevelSensor(
            coordinator, entry_id, name, station_id, unit_system
        ))
    elif station_type == "temp":
        sensors.append(NOAATemperatureSensor(
            coordinator, entry_id, name, station_id, unit_system
        ))
    else:  # buoy
        sensors.append(NOAABuoySensor(
            coordinator, entry_id, name, station_id, unit_system
        ))

    async_add_entities(sensors, True)

class NOAATidesAndCurrentsSensor(CoordinatorEntity, SensorEntity):
    """Representation of a NOAA Tides and Currents sensor."""

    _attr_has_entity_name = True
    _attr_attribution = DEFAULT_ATTRIBUTION

    def __init__(
        self,
        coordinator: NOAATidesDataUpdateCoordinator,
        entry_id: str,
        name: str,
        station_id: str,
        unit_system: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_tides"
        self._attr_name = "Tides"
        self._station_name = name
        self._station_id = station_id
        self._unit_system = unit_system
        self._entry_id = entry_id
        self._station = None
        self.data = None
        self.current_water_level_data = None
        self.attr = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this sensor."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self._station_name,
            manufacturer="NOAA",
            model="Tides and Currents Station",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _extract_coordinator_data(self):
        """Extract predictions and current water level from coordinator data."""
        coordinator_data = self.coordinator.data
        if coordinator_data is None:
            return None, None
        
        if isinstance(coordinator_data, dict):
            predictions = coordinator_data.get("predictions")
            current_water_level = coordinator_data.get("current_water_level")
        else:
            # Legacy data structure (just predictions)
            predictions = coordinator_data
            current_water_level = None
        
        return predictions, current_water_level

    def update_tide_factor_from_attr(self):
        _LOGGER.debug("Updating sine fit for tide factor")
        if self.attr is None:
            return
        if ("last_tide_time" not in self.attr or
            "next_tide_time" not in self.attr or
            "next_tide_type" not in self.attr):
            return
        now = datetime.now()
        most_recent = datetime.strptime(self.attr["last_tide_time"], "%I:%M %p")
        next_tide_time = datetime.strptime(self.attr["next_tide_time"], "%I:%M %p")
        predicted_period = (next_tide_time - most_recent).seconds
        if self.attr["next_tide_type"] == "High":
            self.attr["tide_factor"] = 50 - (50*math.cos((now - most_recent).seconds * math.pi / predicted_period))
        else:
            self.attr["tide_factor"] = 50 + (50*math.cos((now - most_recent).seconds * math.pi / predicted_period))

    @property
    def extra_state_attributes(self):
        """Return the state attributes of this device."""
        _LOGGER.debug("extra_state_attributes queried")
        if self.attr is None:
            self.attr = {}
        
        # Extract predictions and current water level using helper method
        data, current_water_level_data = self._extract_coordinator_data()
        if data is None:
            return self.attr

        # Add current water level data if available from coordinator
        if current_water_level_data is not None and not current_water_level_data.empty:
            try:
                # Get the most recent water level observation
                latest_observation = current_water_level_data.iloc[-1]
                latest_time = current_water_level_data.index[-1]
                # 'water_level' is the renamed column from NOAA API (originally 'v')
                self.attr["current_water_level"] = latest_observation.water_level
                self.attr["current_water_level_time"] = latest_time.strftime("%Y-%m-%dT%H:%M")
            except (IndexError, AttributeError) as err:
                _LOGGER.debug("Could not extract current water level data: %s", err)

        now = datetime.now()
        tide_text = None
        most_recent = None
        for index, row in data.iterrows():
            if most_recent is None or (index <= now and index > most_recent):
                most_recent = index
            elif index > now:
                self.attr["next_tide_time"] = index.strftime("%-I:%M %p")
                self.attr["last_tide_time"] = most_recent.strftime("%-I:%M %p")
                tide_factor = 0
                predicted_period = (index - most_recent).seconds
                if row.hi_lo == "H":
                    self.attr["next_tide_type"] = "High"
                    self.attr["last_tide_type"] = "Low"
                    self.attr["high_tide_level"] = row.predicted_wl
                elif row.hi_lo == "L":
                    self.attr["next_tide_type"] = "Low"
                    self.attr["last_tide_type"] = "High"
                    self.attr["low_tide_level"] = row.predicted_wl
                self.update_tide_factor_from_attr()
                return self.attr
        return self.attr

    @property
    def native_value(self):
        """Return the state of the device."""
        # Extract predictions using helper method
        data, _ = self._extract_coordinator_data()
        if data is None:
            return None
            
        now = datetime.now()
        for index, row in data.iterrows():
            if index > now:
                if row.hi_lo == "H":
                    next_tide = "High"
                if row.hi_lo == "L":
                    next_tide = "Low"
                tide_time = index.strftime("%-I:%M %p")
                return f"{next_tide} tide at {tide_time}"

    def noaa_coops_update(self):
        _LOGGER.debug("update queried.")

        if self._station is None:
            _LOGGER.debug("No station object exists yet- creating one.")
            try:
                self._station = nc.Station(self._station_id)
            except requests.exceptions.ConnectionError as err:
                _LOGGER.error("Couldn't create a NOAA station object. Will retry next update. Error: %s", err)
                self._station = None
                return

        begin = datetime.now() - timedelta(hours=24)
        begin_date = begin.strftime("%Y%m%d %H:%M")
        end = begin + timedelta(hours=48)
        end_date = end.strftime("%Y%m%d %H:%M")
        try:
            df_predictions = self._station.get_data(
                begin_date=begin_date,
                end_date=end_date,
                product="predictions",
                datum="MLLW",
                interval="hilo",
                units=self._unit_system,
                time_zone=self._timezone,
            )

            self.data = df_predictions
            _LOGGER.debug("Data = %s", self.data)
            _LOGGER.debug(
                "Recent Tide data queried with start time set to %s",
                begin_date,
            )
        except ValueError as err:
            _LOGGER.error("Check NOAA Tides and Currents: %s", err.args)
        except requests.exceptions.ConnectionError as err:
            _LOGGER.error("Couldn't connect to NOAA Tides and Currents API: %s", err)

        # Fetch current water level data
        try:
            current_end = datetime.now()
            current_begin = current_end - timedelta(hours=WATER_LEVEL_LOOKBACK_HOURS)
            df_water_level = self._station.get_data(
                begin_date=current_begin.strftime("%Y%m%d %H:%M"),
                end_date=current_end.strftime("%Y%m%d %H:%M"),
                product="water_level",
                datum="MLLW",
                units=self._unit_system,
                time_zone=self._timezone,
            )
            self.current_water_level_data = df_water_level
            _LOGGER.debug(
                "Current water level data retrieved: %d records, latest at %s",
                len(df_water_level) if df_water_level is not None else 0,
                current_end.strftime("%Y%m%d %H:%M"),
            )
        except ValueError as err:
            _LOGGER.debug("Could not fetch current water level data: %s", err.args)
            self.current_water_level_data = None
        except requests.exceptions.ConnectionError as err:
            _LOGGER.debug("Couldn't connect to NOAA Tides and Currents API for water level: %s", err)
            self.current_water_level_data = None
        return None

class NOAACurrentWaterLevelSensor(CoordinatorEntity, SensorEntity):
    """Representation of a NOAA Current Water Level sensor."""

    _attr_has_entity_name = True
    _attr_attribution = DEFAULT_ATTRIBUTION
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: NOAATidesDataUpdateCoordinator,
        entry_id: str,
        name: str,
        station_id: str,
        unit_system: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_current_water_level"
        self._attr_name = "Current Water Level"
        self._station_name = name
        self._station_id = station_id
        self._unit_system = unit_system
        self._entry_id = entry_id
        self._attr_native_unit_of_measurement = (
            UnitOfLength.METERS if unit_system == "metric" else UnitOfLength.FEET
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this sensor."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self._station_name,
            manufacturer="NOAA",
            model="Tides and Currents Station",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _get_current_water_level_data(self):
        """Extract current water level data from coordinator."""
        coordinator_data = self.coordinator.data
        if coordinator_data is None:
            return None
        
        if isinstance(coordinator_data, dict):
            return coordinator_data.get("current_water_level")
        
        return None

    @property
    def extra_state_attributes(self):
        """Return the state attributes of this device."""
        attr = {}
        current_water_level_data = self._get_current_water_level_data()
        
        if current_water_level_data is not None and not current_water_level_data.empty:
            try:
                latest_time = current_water_level_data.index[-1]
                attr["observation_time"] = latest_time.strftime("%Y-%m-%dT%H:%M")
            except (IndexError, AttributeError) as err:
                _LOGGER.debug("Could not extract water level timestamp: %s", err)
        
        return attr

    @property
    def native_value(self):
        """Return the current water level."""
        current_water_level_data = self._get_current_water_level_data()
        
        if current_water_level_data is None or current_water_level_data.empty:
            return None
        
        try:
            # Get the most recent water level observation
            latest_observation = current_water_level_data.iloc[-1]
            # 'water_level' is the renamed column from NOAA API (originally 'v')
            return latest_observation.water_level
        except (IndexError, AttributeError) as err:
            _LOGGER.debug("Could not extract current water level: %s", err)
            return None

class NOAATemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a NOAA Temperature sensor."""

    _attr_has_entity_name = True
    _attr_attribution = DEFAULT_ATTRIBUTION
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(
        self,
        coordinator: NOAATemperatureDataUpdateCoordinator,
        entry_id: str,
        name: str,
        station_id: str,
        unit_system: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_temp"
        self._attr_name = "Water Temperature"
        self._station_name = name
        self._station_id = station_id
        self._unit_system = unit_system
        self._entry_id = entry_id
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.CELSIUS if unit_system == "metric" else UnitOfTemperature.FAHRENHEIT
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this sensor."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self._station_name,
            manufacturer="NOAA",
            model="Temperature Station",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self):
        """Return the state attributes of this device."""
        attr = {}
        data = self.coordinator.data
        if data is None:
            return attr

        if data[0] is not None:
            attr["temperature"] = data[0].water_temp[0]
            attr["temperature_time"] = data[0].index[0].strftime("%Y-%m-%dT%H:%M")
        if data[1] is not None:
            attr["air_temperature"] = data[1].air_temp[0]
            attr["air_temperature_time"] = data[1].index[0].strftime("%Y-%m-%dT%H:%M")
        return attr

    @property
    def native_value(self):
        """Return the state of the device."""
        data = self.coordinator.data
        if data is None:
            return None
        if data[0] is None:
            # If there is no water temperature use the air temperature
            if data[1] is not None:
                return data[1].air_temp[0]
            return None
        return data[0].water_temp[0]


class NOAABuoySensor(CoordinatorEntity, SensorEntity):
    """Representation of a NOAA Buoy."""

    _attr_has_entity_name = True
    _attr_attribution = BUOY_ATTRIBUTION
    _attr_device_class = SensorDeviceClass.TEMPERATURE

    def __init__(
        self,
        coordinator: NOAABuoyDataUpdateCoordinator,
        entry_id: str,
        name: str,
        station_id: str,
        unit_system: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_buoy"
        self._attr_name = "Water Temperature"
        self._station_name = name
        self._station_id = station_id
        self._unit_system = unit_system
        self._entry_id = entry_id
        self._timezone = coordinator.timezone
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.CELSIUS if unit_system == "metric" else UnitOfTemperature.FAHRENHEIT
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this sensor."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self._station_name,
            manufacturer="NDBC",
            model="Buoy Station",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def extra_state_attributes(self):
        """Return the state attributes of this device."""
        attr = {}
        data = self.coordinator.data
        if data is None:
            return attr

        data_time = datetime(data["YY"][1], data["MM"][1], data["DD"][1],
                hour=data["hh"][1], minute=data["mm"][1], tzinfo=tz.utc)
        for k in data:
            if k in ("YY", "MM", "DD", "hh", "mm"):
                continue
            if data[k][1] == "MM":
                # continue here lets us retain the old values when there are no data availabile
                continue

            if self._timezone == "gmt":
                attr[k + "_time"] = data_time.strftime("%Y-%m-%dT%H:%M")
            else:
                attr[k + "_time"] = data_time.replace(tzinfo=tz.utc).astimezone(tz=None).strftime("%Y-%m-%dT%H:%M")

            if self._unit_system == "english" and data[k][0] == "degC":
                attr[k + "_unit"] = "degF"
                attr[k] = round((data[k][1] * 9 / 5) + 32, 1)
            else:
                attr[k + "_unit"] = data[k][0]
                attr[k] = data[k][1]

        return attr

    @property
    def native_value(self):
        """Return the state of the device."""
        data = self.coordinator.data
        if data is None:
            return None
        if "WTMP" not in data or data["WTMP"] is None:
            return None
        if data["WTMP"][1] == "MM":
            return None
        if self._unit_system == "metric":
            return data["WTMP"][1]
        return round((data["WTMP"][1] * 9 / 5) + 32, 1)
