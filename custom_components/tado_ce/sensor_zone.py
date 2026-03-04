"""Tado CE Zone Sensors — temperature, humidity, heating power, overlay, etc."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_hub_device_info, get_zone_device_info
from .format_helpers import (
    format_power_state as _format_power_state,
)

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

class TadoZoneSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Base class for Tado zone sensors (CoordinatorEntity pattern)."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator", zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator)
        self._home_id = coordinator.home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_available = False
        self._attr_native_value = None
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, coordinator.home_id)

    def _get_zone_data(self):
        """Get zone data from coordinator data."""
        try:
            data = self.coordinator.data
            if data:
                zone_states = data.get("zones", {}).get("zoneStates") or {}
                return zone_states.get(self._zone_id)
            return None
        except Exception:
            return None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        zone_data = self._get_zone_data()
        if zone_data:
            self._update_from_zone_data(zone_data)
            self._attr_available = True
        else:
            self._attr_available = False
        self.async_write_ha_state()

    @callback
    def _update_from_zone_data(self, zone_data):
        pass

class TadoTemperatureSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Current temperature sensor."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "Temp"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_temp"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @callback
    def _handle_coordinator_update(self) -> None:
        """Mark unavailable if no temperature data (HOT_WATER combi boilers)."""
        zone_data = self._get_zone_data()
        if zone_data:
            self._update_from_zone_data(zone_data)
            self._attr_available = self._attr_native_value is not None
        else:
            self._attr_available = False
        self.async_write_ha_state()

    @callback
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        sensor_data = zone_data.get('sensorDataPoints') or {}
        self._attr_native_value = (
            (sensor_data.get('insideTemperature') or {}).get('celsius')
        )

class TadoHumiditySensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Humidity sensor."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "Humidity"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_humidity"
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @callback
    def _handle_coordinator_update(self) -> None:
        """Mark unavailable if no humidity data."""
        zone_data = self._get_zone_data()
        if zone_data:
            self._update_from_zone_data(zone_data)
            self._attr_available = self._attr_native_value is not None
        else:
            self._attr_available = False
        self.async_write_ha_state()

    @callback
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        sensor_data = zone_data.get('sensorDataPoints') or {}
        self._attr_native_value = (
            (sensor_data.get('humidity') or {}).get('percentage')
        )

class TadoHeatingPowerSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Heating power sensor."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "Heating"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_heating"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:radiator"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @callback
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        activity_data = zone_data.get('activityDataPoints') or {}
        power = (activity_data.get('heatingPower') or {}).get('percentage')
        self._attr_native_value = power if power is not None else 0

class TadoACPowerSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """AC power sensor."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "AIR_CONDITIONING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "AC"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_ac"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_icon = "mdi:air-conditioner"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @callback
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for these fields)
        activity_data = zone_data.get('activityDataPoints') or {}
        ac_power = activity_data.get('acPower') or {}
        # Try percentage first (older API), then value (newer API returns 'ON'/'OFF')
        power = ac_power.get('percentage')
        if power is None:
            value = ac_power.get('value')
            power = 100 if value == 'ON' else 0
        self._attr_native_value = power if power is not None else 0

class TadoBoilerFlowTemperatureSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Boiler flow temperature sensor - reads from HEATING zones.

    This is a Hub-level sensor that reads boilerFlowTemperature from
    any HEATING zone that has this data available.
    """

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "[CE] Boiler Flow Temp"
        self.entity_id = "sensor.tado_ce_boiler_flow_temperature"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_boiler_flow_temp"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:water-boiler"
        self._attr_device_info = get_hub_device_info(coordinator.home_id)
        self._attr_available = False
        self._attr_native_value = None
        self._source_zone = None

    @property
    def extra_state_attributes(self):
        return {
            "source_zone": self._source_zone,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        try:
            data = self.coordinator.data
            if not data:
                self._attr_available = False
                self.async_write_ha_state()
                return

            zone_states = data.get("zones", {}).get("zoneStates") or {}
            for zone_id, zone_data in zone_states.items():
                activity_data = zone_data.get('activityDataPoints') or {}
                flow_temp = (activity_data.get('boilerFlowTemperature') or {}).get('celsius')
                if flow_temp is not None:
                    self._attr_native_value = flow_temp
                    self._source_zone = zone_id
                    self._attr_available = True
                    self.async_write_ha_state()
                    return

            self._attr_native_value = None
            self._source_zone = None
            self._attr_available = False
        except Exception:
            self._attr_available = False
        self.async_write_ha_state()

class TadoTargetTempSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Target temperature sensor."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Target"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_target"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_icon = "mdi:thermometer-check"

    @callback
    def _update_from_zone_data(self, zone_data):
        # Use 'or {}' pattern for null safety (API may return null for setting)
        setting = zone_data.get('setting') or {}
        if setting.get('power') == 'ON':
            self._attr_native_value = (setting.get('temperature') or {}).get('celsius')
        else:
            self._attr_native_value = None

class TadoOverlaySensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Overlay status sensor (Manual/Schedule)."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Overlay"
        # Use zone_name for unique_id to maintain entity_id stability
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_overlay"
        self._attr_icon = "mdi:calendar-clock"
        self._next_change = None
        self._next_temp = None

    @property
    def extra_state_attributes(self):
        return {
            "next_change": self._next_change,
            "next_temperature": self._next_temp,
        }

    @callback
    def _update_from_zone_data(self, zone_data):
        overlay_type = zone_data.get('overlayType')
        # Use 'or {}' pattern for null safety
        setting = zone_data.get('setting') or {}
        power = setting.get('power')

        if power == 'OFF':
            self._attr_native_value = "Off"
        elif overlay_type == 'MANUAL':
            self._attr_native_value = "Manual"
        else:
            self._attr_native_value = "Schedule"

        # Next schedule change
        next_change = zone_data.get('nextScheduleChange')
        if next_change:
            self._next_change = next_change.get('start')
            next_setting = next_change.get('setting')
            if next_setting:
                temp = next_setting.get('temperature')
                self._next_temp = temp.get('celsius') if temp else None
            else:
                self._next_temp = None
        else:
            self._next_change = None
            self._next_temp = None


class TadoHotWaterPowerSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Hot water power sensor (ON/OFF)."""

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HOT_WATER"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Power"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_power"
        self._attr_icon = "mdi:power"

    @callback
    def _update_from_zone_data(self, zone_data):
        setting = zone_data.get('setting') or {}
        power = setting.get('power')
        self._attr_native_value = _format_power_state(power) if power else "Unknown"

