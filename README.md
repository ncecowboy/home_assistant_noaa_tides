# NOAA Tides and Currents Sensor for Home-Assistant

This library is a [fork of the core component](https://www.home-assistant.io/integrations/noaa_tides/) which adds some additional features and migrates the backend from the now-defunct [py_noaa](https://github.com/GClunies/py_noaa) to the superseding [noaa_coops](https://github.com/GClunies/noaa_coops).

## Features

- **UI Configuration**: Easy setup through Home Assistant UI (Config Flow)
- **YAML Configuration**: Still supported for backward compatibility
- **HACS Compatible**: Install and manage through HACS
- **Automated Releases**: Version management through GitHub Actions
- Multiple sensor types: Tides, Water Temperature, Buoy data, and Current Water Level

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add `https://github.com/ncecowboy/home_assistant_noaa_tides` as an Integration
6. Click "Install"
7. Restart Home Assistant

### Manual Installation

1. Clone the repository.
2. Copy the `noaa_tides` directory into `<home assistant directory>/custom_components/`
3. Restart Home Assistant

## Configuration

### UI Configuration (Recommended)

1. Go to **Settings** > **Devices & Services**
2. Click **+ Add Integration**
3. Search for "NOAA Tides"
4. Follow the configuration prompts:
   - **Station Type**: Choose `tides`, `temp`, or `buoy`
   - **Entry Method**: Choose how you want to find your station:
     - **Browse stations by state** (recommended for tides/temp): Select your state, then choose from a list of available stations
     - **Enter station ID manually**: Directly enter a station ID (required for buoy type)
   - **State** (if using lookup): Select your state from the dropdown
   - **Station** (if using lookup): Select your station from the filtered list
   - **Station ID** (if manual entry): Station ID from [NOAA Tides and Currents](https://tidesandcurrents.noaa.gov/) (for tides/temp) or [NDBC](https://www.ndbc.noaa.gov/) (for buoy). The station will be verified before proceeding.
   - **Name**: Friendly name for the sensor (optional)

**Note**: Time zone and unit system are automatically configured from your Home Assistant system settings. The integration will use local standard/daylight time (`lst_ldt`) for timestamps and will match your Home Assistant unit preferences (metric or imperial).

You can configure multiple sensors by repeating this process with different station IDs.

### YAML Configuration (Legacy)

For backward compatibility, YAML configuration is still supported. Add to your `configuration.yaml`:

**Note**: When using UI configuration (recommended), time zone and unit system are automatically derived from Home Assistant system settings. For YAML configuration, you can still manually specify these values if desired, but they will default to system settings if not provided.

``` yaml
sensor:
  - platform: noaa_tides
    name: tides           # Useful when more than one sensor is used. Otherwise a name is generated.
    station_id: 8512354   # A station ID from https://tidesandcurrents.noaa.gov/
    type: tides           # This station will be used to measure water level
    scan_interval: 360    # Polling interval for the NOAA API

  - platform: noaa_tides
    station_id: 8510560
    type: temp            # This station will be used to measure water temperature
    name: water_temp
    scan_interval: 360

  - platform: noaa_tides
    name: buoy
    type: buoy            # This station will be used for off-shore Buoy data
    station_id: 44017     # A buoy ID from https://www.ndbc.noaa.gov/
    scan_interval: 360
```

Different stations support different features (products/datums), so use the [station finder](https://tidesandcurrents.noaa.gov/) to select the right station for `tides` vs `temp` types.

## Available Sensors and Attributes

### Tides Station Sensors

When you configure a `tides` type station, you will get **two sensors**:

#### 1. Tides Sensor

The main tides sensor shows the next predicted tide event and provides the following attributes:

- **`next_tide_time`**: Time of the next high or low tide (e.g., "3:45 PM")
- **`next_tide_type`**: Type of next tide ("High" or "Low")
- **`last_tide_time`**: Time of the last high or low tide (e.g., "9:30 AM")
- **`last_tide_type`**: Type of last tide ("High" or "Low")
- **`high_tide_level`**: Predicted water level at high tide (in feet or meters)
- **`low_tide_level`**: Predicted water level at low tide (in feet or meters)
- **`tide_factor`**: Calculated tide position between 0-100% (based on sine curve between last and next tide)
- **`current_water_level`**: Current observed water level (in feet or meters, updates with scan interval)
- **`current_water_level_time`**: Timestamp of the current water level observation (ISO 8601 format)

#### 2. Current Water Level Sensor

A dedicated sensor for the current observed water level at the station. This sensor:

- Shows the **current water level** as its main state (in feet or meters)
- Updates with the scan interval (every hour by default)
- Has device class `distance` for proper Home Assistant integration
- Includes an **`observation_time`** attribute with the timestamp of the observation (ISO 8601 format)

### Temperature Sensor Attributes

- **`temperature`**: Current water temperature
- **`temperature_time`**: Timestamp of water temperature reading
- **`air_temperature`**: Current air temperature at the station
- **`air_temperature_time`**: Timestamp of air temperature reading

### Buoy Sensor Attributes

Buoy sensors provide various meteorological and oceanographic data depending on the specific buoy. Common attributes include wave height, wave period, wind speed, air pressure, and water temperature.

## Usage Examples

### Template Sensors
For complex lovelace widgets, it is suggested to use the [template platform](https://www.home-assistant.io/integrations/template/).

```yaml
template:
  - sensor:
      - name: "Next tide"
        state: "{{ state_attr('sensor.tides', 'next_tide_type') }} tide at {{ state_attr('sensor.tides', 'next_tide_time') }}"
        icon: "{% if is_state_attr('sensor.tides', 'next_tide_type', 'High') %}mdi:waves{% else %}mdi:wave{% endif %}"
      - name: "Last tide"
        state: "{{ state_attr('sensor.tides', 'last_tide_type') }} tide at {{ state_attr('sensor.tides', 'last_tide_time') }}"
        icon: "{% if is_state_attr('sensor.tides', 'last_tide_type', 'High') %}mdi:waves{% else %}mdi:wave{% endif %}"
      - name: "Water level"
        state: "{{ state_attr('sensor.tides', 'tide_factor') }}"
        unit_of_measurement: '%'
      - name: "Beach air temp"
        state: "{{ state_attr('sensor.water_temp', 'air_temperature') }}"
```

**Note**: The current water level is now available as a dedicated sensor (e.g., `sensor.current_water_level`) and no longer needs a template sensor. You can use it directly in your dashboards!

Note that the tide curve requires `sensor.internet_time` to be updated correctly. Use the `time_date` sensor platform like this:

``` yaml
  - platform: time_date
    display_options:
      - 'beat'
```

I'm also using the [custom mini-graph card](https://github.com/kalkih/mini-graph-card) with the following lovelace configuration:
``` yaml
          - entities:
              - color: '#02ace5'
                entity: sensor.beach_air_temp
                name: Air
                show_state: true
                state_adaptive_color: true
              - color: darkblue
                entity: sensor.water_temp
                name: Water
                show_state: true
                state_adaptive_color: true
            hours_to_show: 24
            name: Air and Water Temperatures
            points_per_hour: 12
            show:
              fill: false
            type: 'custom:mini-graph-card'
            unit: °F
          - entities:
              - entity: sensor.next_tide
              - entity: sensor.last_tide
            footer:
              entities:
                - sensor.water_level
              hours_to_show: 12
              icon: 'mdi:swim'
              line_color: darkblue
              lower_bound: 0
              points_per_hour: 60
              show:
                labels: false
              type: 'custom:mini-graph-card'
              upper_bound: 100
            title: Tides
            type: entities
```

Which looks like this:

![Lovelace Configuration](/noaa_tides_lovelace.png)

## Support

For setup and other support questions, see the [Home Assistant community discussion for this add-on](https://community.home-assistant.io/t/i-made-an-improved-noaa-tides-sensor-for-my-familys-summer-house/203466).

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

Please make sure to update tests as appropriate.

## License
[MIT](https://choosealicense.com/licenses/mit/)
