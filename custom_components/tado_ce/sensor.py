"""Tado CE Sensors — platform entry point.

Sub-modules:
- sensor_zone.py: zone-level sensors (temperature, humidity, heating power, overlay)
- sensor_environment.py: mold risk, condensation, comfort, dew point, surface temp
- sensor_device.py: battery, connection sensors
- sensor_hub.py: API usage, home info sensors
- sensor_insight.py: home/zone insights sensors
- sensor_insight_collector.py: insight collection logic
- sensor_smart_comfort.py: smart comfort sensors
- sensor_thermal.py: thermal analytics sensors
- sensor_weather.py: weather sensors
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.components.sensor import SensorEntity
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .config_manager import ConfigurationManager
    from .coordinator import TadoConfigEntry, TadoDataUpdateCoordinator
    from .data_loader import DataLoader

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
    TadoTemperatureSensor,  # Re-exported for base class
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


def _create_common_zone_sensors(
    coordinator: TadoDataUpdateCoordinator,
    zone_id: str,
    zone_name: str,
    zone_type: str,
    config_manager: ConfigurationManager,
) -> list[SensorEntity]:
    """Create sensors common to HEATING and AC zones."""
    sensors: list[SensorEntity] = [
        TadoTemperatureSensor(coordinator, zone_id, zone_name, zone_type),
        TadoHumiditySensor(coordinator, zone_id, zone_name, zone_type),
        TadoTargetTempSensor(coordinator, zone_id, zone_name, zone_type),
        TadoOverlaySensor(coordinator, zone_id, zone_name, zone_type),
    ]
    sensors.append(TadoZoneInsightsSensor(coordinator, zone_id, zone_name, zone_type))
    if config_manager.get_environment_sensors_enabled():
        sensors.extend(
            [
                TadoMoldRiskSensor(coordinator, zone_id, zone_name, zone_type),
                TadoMoldRiskPercentageSensor(coordinator, zone_id, zone_name, zone_type),
                TadoComfortLevelSensor(coordinator, zone_id, zone_name, zone_type),
                TadoCondensationRiskSensor(coordinator, zone_id, zone_name, zone_type),
                TadoSurfaceTemperatureSensor(coordinator, zone_id, zone_name, zone_type),
                TadoDewPointSensor(coordinator, zone_id, zone_name, zone_type),
            ],
        )
    if config_manager.get_smart_comfort_enabled():
        sensors.extend(
            [
                TadoScheduleDeviationSensor(coordinator, zone_id, zone_name, zone_type),
                TadoNextScheduleTimeSensor(coordinator, zone_id, zone_name, zone_type),
                TadoNextScheduleTempSensor(coordinator, zone_id, zone_name, zone_type),
                TadoPreheatAdvisorSensor(coordinator, zone_id, zone_name, zone_type),
                TadoSmartComfortTargetSensor(coordinator, zone_id, zone_name, zone_type),
            ],
        )
    return sensors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE sensors from a config entry."""
    coordinator = entry.runtime_data
    config_manager = coordinator.config_manager
    data_loader = coordinator.data_loader

    # Build zone_names from coordinator data
    zones_info = coordinator.data.get("zones_info") or []
    zone_names = {str(z.get("id")): z.get("name", f"Zone {z.get('id')}") for z in zones_info}

    sensors: list[SensorEntity] = []

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
            zone_types = {str(z.get("id")): z.get("type", "HEATING") for z in zones_info}

        zones_with_heating_power = set()

        if zones_data:
            zone_states = zones_data.get("zoneStates") or {}

            for zone_id, zone_data in zone_states.items():
                activity_data = zone_data.get("activityDataPoints") or {}
                heating_power = activity_data.get("heatingPower")
                if heating_power is not None:
                    zones_with_heating_power.add(zone_id)

            if zones_with_heating_power:
                _LOGGER.debug("Zones with heatingPower data: %s", zones_with_heating_power)

            for zone_id, zone_data in zone_states.items():
                zone_type = zone_types.get(zone_id, "HEATING")
                zone_name = zone_names.get(zone_id, f"Zone {zone_id}")

                sensor_data = zone_data.get("sensorDataPoints") or {}
                inside_temp = sensor_data.get("insideTemperature") or {}
                has_temperature = inside_temp.get("celsius") is not None

                if zone_type == "HEATING":
                    sensors.extend(
                        _create_common_zone_sensors(
                            coordinator, zone_id, zone_name, zone_type, config_manager,
                        ),
                    )
                    if config_manager.get_zone_diagnostics_enabled():
                        sensors.append(TadoHeatingPowerSensor(coordinator, zone_id, zone_name, zone_type))
                    thermal_analytics_zones = config_manager.get_thermal_analytics_zones()
                    zone_thermal_enabled = (not thermal_analytics_zones) or (zone_id in thermal_analytics_zones)
                    if (
                        config_manager.get_thermal_analytics_enabled()
                        and zone_id in zones_with_heating_power
                        and zone_thermal_enabled
                    ):
                        if coordinator.heating_cycle_coordinator:
                            hcc = coordinator.heating_cycle_coordinator
                            sensors.extend(
                                [
                                    TadoThermalInertiaSensor(
                                        coordinator.home_id, hcc, zone_id, zone_name, zone_type,
                                    ),
                                    TadoHeatingRateSensor(
                                        coordinator.home_id, hcc, zone_id, zone_name, zone_type,
                                    ),
                                    TadoPreheatTimeSensor(
                                        coordinator.home_id, hcc, zone_id, zone_name, zone_type,
                                    ),
                                    TadoConfidenceSensor(
                                        coordinator.home_id, hcc, zone_id, zone_name, zone_type,
                                    ),
                                    TadoHeatingAccelerationSensor(
                                        coordinator.home_id, hcc, zone_id, zone_name, zone_type,
                                    ),
                                    TadoApproachFactorSensor(
                                        coordinator.home_id, hcc, zone_id, zone_name, zone_type,
                                    ),
                                ],
                            )
                        else:
                            _LOGGER.warning(
                                "Zone %s has heatingPower but HeatingCycleCoordinator "
                                "not available - thermal analytics sensors not created",
                                zone_name,
                            )
                    # Smart comfort sensors already included by _create_common_zone_sensors

                elif zone_type == "AIR_CONDITIONING":
                    sensors.extend(
                        _create_common_zone_sensors(
                            coordinator, zone_id, zone_name, zone_type, config_manager,
                        ),
                    )
                    sensors.append(TadoACPowerSensor(coordinator, zone_id, zone_name, zone_type))
                elif zone_type == "HOT_WATER":
                    if has_temperature:
                        sensors.append(TadoTemperatureSensor(coordinator, zone_id, zone_name, zone_type))
                    sensors.append(TadoOverlaySensor(coordinator, zone_id, zone_name, zone_type))
                    sensors.append(TadoHotWaterPowerSensor(coordinator, zone_id, zone_name, zone_type))
    except Exception:
        _LOGGER.exception("Failed to load zones")

    # Device sensors (battery + connection)
    if config_manager.get_zone_diagnostics_enabled():
        try:
            zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)
            if zones_info:
                device_zones: dict[str, list[tuple]] = {}  # type: ignore[type-arg]
                for zone in zones_info:
                    zone_id = str(zone.get("id"))
                    zone_name = zone.get("name", f"Zone {zone_id}")
                    zone_type = zone.get("type", "HEATING")
                    # Tado API may return null for 'devices'; 'or []' handles None correctly
                    for device in zone.get("devices") or []:
                        serial = device.get("shortSerialNo")
                        if serial:
                            if serial not in device_zones:
                                device_zones[serial] = []
                            device_zones[serial].append((zone_id, zone_name, zone_type, device))

                for zone_list in device_zones.values():

                    def zone_priority(item: tuple[Any, ...]) -> int:
                        """Return the priority order for zone sensor creation."""
                        zt = item[2]
                        if zt == "HEATING":
                            return 0
                        if zt == "AIR_CONDITIONING":
                            return 1
                        return 2

                    zone_list.sort(key=zone_priority)
                    zone_id, zone_name, zone_type, device = zone_list[0]

                    if "batteryState" in device:
                        sensors.append(
                            TadoBatterySensor(
                                coordinator,
                                zone_id,
                                zone_name,
                                zone_type,
                                device,
                                zones_info,
                            ),
                        )
                    if "connectionState" in device:
                        sensors.append(
                            TadoDeviceConnectionSensor(
                                coordinator,
                                zone_id,
                                zone_name,
                                zone_type,
                                device,
                                zones_info,
                            ),
                        )
        except Exception as e:
            _LOGGER.warning("Failed to load device info: %s", e)

    async_add_entities(sensors, True)
    _LOGGER.info("Tado CE sensors loaded: %s", len(sensors))


def _has_boiler_flow_temperature_data(data_loader: DataLoader) -> bool:
    """Check if any zone has boiler flow temperature data (requires OpenTherm)."""
    try:
        data = data_loader.load_zones_file()
        if not data:
            return False

        zone_states = data.get("zoneStates") or {}
        for zone_id, zone_data in zone_states.items():
            activity_data = zone_data.get("activityDataPoints") or {}
            flow_temp = (activity_data.get("boilerFlowTemperature") or {}).get("celsius")
            if flow_temp is not None:
                _LOGGER.debug("Found boilerFlowTemperature in zone %s: %s°C", zone_id, flow_temp)
                return True

        return False
    except Exception as e:
        _LOGGER.debug("Error checking boiler flow temperature data: %s", e)
        return False
