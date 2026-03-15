"""Tado CE Bridge Sensors — boiler wiring state and output temperature.

Reads bridge API data from coordinator.data["bridge"] (populated by
_async_fetch_bridge_data). Only created when bridge credentials
(bridge_serial + bridge_auth_key) are present in config entry options.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_hub_device_info
from .entity_registry import ENTITY_REGISTRY, get_entity_category

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoBridgeBaseSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    """Base class for Tado CE bridge sensors.

    Follows the same pattern as TadoHubSensor: common init with
    device_info on the hub device, _handle_coordinator_update -> update().
    Subclasses set sensor-specific attrs in __init__ and implement update().
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the TadoBridgeBaseSensor."""
        super().__init__(coordinator)
        self._attr_device_info = get_hub_device_info(coordinator.home_id)
        self._attr_available = False
        self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data update."""
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator data. Override in subclasses."""


class TadoBoilerWiringStateSensor(TadoBridgeBaseSensor):
    """Sensor showing boiler wiring installation state from Bridge API."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the TadoBoilerWiringStateSensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_boiler_wiring_state"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        if _meta.icon:
            self._attr_icon = _meta.icon
        self._attr_entity_category = get_entity_category(_meta)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return extra state attributes from bridge data."""
        bridge: dict[str, object] = self.coordinator.data.get("bridge") or {}
        attrs: dict[str, object] = {}
        if "deviceType" in bridge:
            attrs["device_type"] = bridge["deviceType"]
        if "serialNo" in bridge:
            attrs["serial"] = bridge["serialNo"]
        if "connectionType" in bridge:
            attrs["connection_type"] = bridge["connectionType"]
        if "isConnected" in bridge:
            attrs["connected"] = bridge["isConnected"]
        if "hotWaterZonePresent" in bridge:
            attrs["hot_water_zone_present"] = bridge["hotWaterZonePresent"]
        return attrs

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator bridge data."""
        bridge = self.coordinator.data.get("bridge")
        if not bridge:
            self._attr_available = False
            return
        state = bridge.get("state")
        if state is not None:
            self._attr_native_value = str(state)
            self._attr_available = True
        else:
            self._attr_available = False


class TadoBoilerOutputTemperatureSensor(TadoBridgeBaseSensor):
    """Sensor showing current boiler output temperature from Bridge API."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the TadoBoilerOutputTemperatureSensor."""
        super().__init__(coordinator)
        _meta = ENTITY_REGISTRY["sensor_boiler_output_temperature"]
        self._attr_translation_key = _meta.translation_key
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_{_meta.unique_id_suffix}"
        if _meta.icon:
            self._attr_icon = _meta.icon
        self._attr_entity_category = get_entity_category(_meta)

    @callback
    def update(self) -> None:
        """Update sensor state from coordinator bridge data."""
        bridge = self.coordinator.data.get("bridge")
        if not bridge:
            self._attr_available = False
            return
        temp = bridge.get("boilerMaxOutputTemperatureInCelsius")
        if temp is not None:
            self._attr_native_value = float(temp)
            self._attr_available = True
        else:
            self._attr_available = False
