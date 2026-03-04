"""Tado CE Sensors — platform entry point.

Flattened from sensor/ sub-package to root-level modules:
- sensor.py: async_setup_entry (this file)
- sensor_zone.py: TadoZoneSensor base + zone-level sensors
- sensor_environment.py: Mold risk, condensation, comfort, dew point, surface temp
- sensor_device.py: Battery, connection sensors
- sensor_hub.py: API usage, home info sensors
- sensor_insight.py: Home/zone insights sensors
- sensor_insight_collector.py: Insight collection logic
- sensor_smart_comfort.py: Smart comfort sensors
- sensor_thermal.py: Thermal analytics sensors
- sensor_weather.py: Weather sensors
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TadoDataUpdateCoordinator

# Device sensors (2 classes)
from .sensor_device import (
    TadoBatterySensor,
    TadoDeviceConnectionSensor,
)

# Environment sensors (6 classes)
from .sensor_environment import (
    TadoComfortLevelSensor,
    TadoCondensationRiskSensor,
    TadoDewPointSensor,
    TadoMoldRiskPercentageSensor,
    TadoMoldRiskSensor,
    TadoSurfaceTemperatureSensor,
)

# Hub sensors (12 classes)
from .sensor_hub import (
    TadoApiBreakdownSensor,
    TadoApiHistorySensor,
    TadoApiLimitSensor,
    TadoApiResetSensor,
    TadoApiStatusSensor,
    TadoApiUsageSensor,
    TadoHomeIdSensor,
    TadoLastSyncSensor,
    TadoNextSyncSensor,
    TadoPollingIntervalSensor,
    TadoTokenStatusSensor,
    TadoZoneCountSensor,
)

# Insight sensors (2 classes)
from .sensor_insight import (
    TadoHomeInsightsSensor,
    TadoZoneInsightsSensor,
)

# Smart Comfort sensors (5 classes)
from .sensor_smart_comfort import (
    TadoNextScheduleTempSensor,
    TadoNextScheduleTimeSensor,
    TadoPreheatAdvisorSensor,
    TadoScheduleDeviationSensor,
    TadoSmartComfortTargetSensor,
)

# Thermal sensors (6 classes)
from .sensor_thermal import (
    TadoApproachFactorSensor,
    TadoConfidenceSensor,
    TadoHeatingAccelerationSensor,
    TadoHeatingRateSensor,
    TadoPreheatTimeSensor,
    TadoThermalInertiaSensor,
)

# Weather sensors (3 classes)
from .sensor_weather import (
    TadoOutsideTemperatureSensor,
    TadoSolarIntensitySensor,
    TadoWeatherStateSensor,
)

# Zone sensors (base + 8 classes)
from .sensor_zone import (
    TadoACPowerSensor,
    TadoBoilerFlowTemperatureSensor,
    TadoHeatingPowerSensor,
    TadoHotWaterPowerSensor,
    TadoHumiditySensor,
    TadoOverlaySensor,
    TadoTargetTempSensor,
    TadoTemperatureSensor,
    TadoZoneSensor,  # Re-exported for base class
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
):
    """Set up Tado CE sensors from a config entry."""
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    config_manager = coordinator.config_manager
    data_loader = coordinator.data_loader

    zone_names = await hass.async_add_executor_job(data_loader.get_zone_names)

    sensors = []

    # Hub sensors (API status, home info)
    sensors.append(TadoHomeIdSensor(coordinator))
    sensors.append(TadoApiUsageSensor(coordinator))
    sensors.append(TadoApiLimitSensor(coordinator))
    sensors.append(TadoApiResetSensor(coordinator))
    sensors.append(TadoApiStatusSensor(coordinator))
    sensors.append(TadoTokenStatusSensor(coordinator))
    sensors.append(TadoZoneCountSensor(coordinator))
    sensors.append(TadoLastSyncSensor(coordinator))

    # API Monitoring Sensors
    sensors.append(TadoNextSyncSensor(coordinator))
    sensors.append(TadoPollingIntervalSensor(coordinator))
    sensors.append(TadoApiHistorySensor(coordinator))
    sensors.append(TadoApiBreakdownSensor(coordinator))
    # Home Insights aggregation sensor
    sensors.append(TadoHomeInsightsSensor(coordinator))

    # Boiler Flow Temperature sensor (Hub device - only if data available)
    if await hass.async_add_executor_job(_has_boiler_flow_temperature_data, data_loader):
        _LOGGER.info("Boiler flow temperature data detected - creating sensor")
        sensors.append(TadoBoilerFlowTemperatureSensor(coordinator))
    else:
        _LOGGER.debug("No boiler flow temperature data found - sensor not created (requires OpenTherm)")

    # Weather sensors (optional based on configuration)
    if config_manager.get_weather_enabled():
        sensors.append(TadoOutsideTemperatureSensor(coordinator))
        sensors.append(TadoSolarIntensitySensor(coordinator))
        sensors.append(TadoWeatherStateSensor(coordinator))

    # Zone sensors
    try:
        zones_data = await hass.async_add_executor_job(data_loader.load_zones_file)
        zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

        # Build zone type map
        zone_types = {}
        if zones_info:
            zone_types = {str(z.get('id')): z.get('type', 'HEATING') for z in zones_info}

        zones_with_heating_power = set()

        if zones_data:
            zone_states = zones_data.get('zoneStates') or {}

            for zone_id, zone_data in zone_states.items():
                activity_data = zone_data.get('activityDataPoints') or {}
                heating_power = activity_data.get('heatingPower')
                if heating_power is not None:
                    zones_with_heating_power.add(zone_id)

            if zones_with_heating_power:
                _LOGGER.debug("Zones with heatingPower data: %s", zones_with_heating_power)

            for zone_id, zone_data in zone_states.items():
                zone_type = zone_types.get(zone_id, 'HEATING')
                zone_name = zone_names.get(zone_id, f"Zone {zone_id}")

                sensor_data = zone_data.get('sensorDataPoints') or {}
                inside_temp = sensor_data.get('insideTemperature') or {}
                has_temperature = inside_temp.get('celsius') is not None

                if zone_type == 'HEATING':
                    sensors.extend([
                        TadoTemperatureSensor(coordinator, zone_id, zone_name, zone_type),
                        TadoHumiditySensor(coordinator, zone_id, zone_name, zone_type),
                        TadoTargetTempSensor(coordinator, zone_id, zone_name, zone_type),
                        TadoOverlaySensor(coordinator, zone_id, zone_name, zone_type),
                    ])
                    sensors.append(TadoZoneInsightsSensor(coordinator, zone_id, zone_name, zone_type))
                    if config_manager.get_zone_diagnostics_enabled():
                        sensors.append(TadoHeatingPowerSensor(coordinator, zone_id, zone_name, zone_type))
                    if config_manager.get_environment_sensors_enabled():
                        sensors.extend([
                            TadoMoldRiskSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoMoldRiskPercentageSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoComfortLevelSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoCondensationRiskSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoSurfaceTemperatureSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoDewPointSensor(coordinator, zone_id, zone_name, zone_type),
                        ])
                    thermal_analytics_zones = config_manager.get_thermal_analytics_zones()
                    zone_thermal_enabled = (not thermal_analytics_zones) or (zone_id in thermal_analytics_zones)
                    if (config_manager.get_thermal_analytics_enabled()
                            and zone_id in zones_with_heating_power
                            and zone_thermal_enabled):
                        if coordinator.heating_cycle_coordinator:
                            hcc = coordinator.heating_cycle_coordinator
                            sensors.extend([
                                TadoThermalInertiaSensor(
                                    coordinator.home_id, hcc, zone_id, zone_name, zone_type),
                                TadoHeatingRateSensor(
                                    coordinator.home_id, hcc, zone_id, zone_name, zone_type),
                                TadoPreheatTimeSensor(
                                    coordinator.home_id, hcc, zone_id, zone_name, zone_type),
                                TadoConfidenceSensor(
                                    coordinator.home_id, hcc, zone_id, zone_name, zone_type),
                                TadoHeatingAccelerationSensor(
                                    coordinator.home_id, hcc, zone_id, zone_name, zone_type),
                                TadoApproachFactorSensor(
                                    coordinator.home_id, hcc, zone_id, zone_name, zone_type),
                            ])
                        else:
                            _LOGGER.warning(
                                "Zone %s has heatingPower but HeatingCycleCoordinator "
                                "not available - thermal analytics sensors not created",
                                zone_name
                            )
                    if config_manager.get_smart_comfort_enabled():
                        sensors.extend([
                            TadoScheduleDeviationSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoNextScheduleTimeSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoNextScheduleTempSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoPreheatAdvisorSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoSmartComfortTargetSensor(coordinator, zone_id, zone_name, zone_type),
                        ])

                elif zone_type == 'AIR_CONDITIONING':
                    sensors.extend([
                        TadoTemperatureSensor(coordinator, zone_id, zone_name, zone_type),
                        TadoHumiditySensor(coordinator, zone_id, zone_name, zone_type),
                        TadoACPowerSensor(coordinator, zone_id, zone_name, zone_type),
                        TadoTargetTempSensor(coordinator, zone_id, zone_name, zone_type),
                        TadoOverlaySensor(coordinator, zone_id, zone_name, zone_type),
                    ])
                    sensors.append(TadoZoneInsightsSensor(coordinator, zone_id, zone_name, zone_type))
                    if config_manager.get_environment_sensors_enabled():
                        sensors.extend([
                            TadoMoldRiskSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoMoldRiskPercentageSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoComfortLevelSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoCondensationRiskSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoSurfaceTemperatureSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoDewPointSensor(coordinator, zone_id, zone_name, zone_type),
                        ])
                    if config_manager.get_smart_comfort_enabled():
                        sensors.extend([
                            TadoScheduleDeviationSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoNextScheduleTimeSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoNextScheduleTempSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoPreheatAdvisorSensor(coordinator, zone_id, zone_name, zone_type),
                            TadoSmartComfortTargetSensor(coordinator, zone_id, zone_name, zone_type),
                        ])
                elif zone_type == 'HOT_WATER':
                    if has_temperature:
                        sensors.append(TadoTemperatureSensor(coordinator, zone_id, zone_name, zone_type))
                    sensors.append(TadoOverlaySensor(coordinator, zone_id, zone_name, zone_type))
                    sensors.append(TadoHotWaterPowerSensor(coordinator, zone_id, zone_name, zone_type))
    except Exception as e:
        _LOGGER.error("Failed to load zones: %s", e)

    # Device sensors (battery + connection)
    if config_manager.get_zone_diagnostics_enabled():
        try:
            zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)
            if zones_info:
                device_zones: dict[str, list[tuple]] = {}
                for zone in zones_info:
                    zone_id = str(zone.get('id'))
                    zone_name = zone.get('name', f"Zone {zone_id}")
                    zone_type = zone.get('type', 'HEATING')
                    for device in zone.get('devices', []):
                        serial = device.get('shortSerialNo')
                        if serial:
                            if serial not in device_zones:
                                device_zones[serial] = []
                            device_zones[serial].append((zone_id, zone_name, zone_type, device))

                for serial, zone_list in device_zones.items():
                    def zone_priority(item):
                        zt = item[2]
                        if zt == 'HEATING':
                            return 0
                        elif zt == 'AIR_CONDITIONING':
                            return 1
                        return 2

                    zone_list.sort(key=zone_priority)
                    zone_id, zone_name, zone_type, device = zone_list[0]

                    if 'batteryState' in device:
                        sensors.append(TadoBatterySensor(
                            coordinator, zone_id, zone_name, zone_type, device
                        ))
                    if 'connectionState' in device:
                        sensors.append(TadoDeviceConnectionSensor(
                            coordinator, zone_id, zone_name, zone_type, device
                        ))
        except Exception as e:
            _LOGGER.warning("Failed to load device info: %s", e)

    async_add_entities(sensors, True)
    _LOGGER.info("Tado CE sensors loaded: %s", len(sensors))


def _has_boiler_flow_temperature_data(data_loader):
    """Check if any zone has boiler flow temperature data (requires OpenTherm)."""
    try:
        data = data_loader.load_zones_file()
        if not data:
            return False

        zone_states = data.get('zoneStates') or {}
        for zone_id, zone_data in zone_states.items():
            activity_data = zone_data.get('activityDataPoints') or {}
            flow_temp = (activity_data.get('boilerFlowTemperature') or {}).get('celsius')
            if flow_temp is not None:
                _LOGGER.debug("Found boilerFlowTemperature in zone %s: %s°C", zone_id, flow_temp)
                return True

        return False
    except Exception as e:
        _LOGGER.debug("Error checking boiler flow temperature data: %s", e)
        return False
