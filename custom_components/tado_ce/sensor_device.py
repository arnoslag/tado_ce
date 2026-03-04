"""Tado CE Device Sensors — battery and connection status."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_zone_device_info
from .format_helpers import (
    format_battery_state as _format_battery_state,
)
from .format_helpers import (
    format_connection_state as _format_connection_state,
)
from .format_helpers import (
    format_connection_state_attr as _format_connection_state_attr,
)
from .insights import (
    calculate_battery_recommendation,
    calculate_connection_recommendation,
)

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoBatterySensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Battery status sensor."""

    def __init__(
        self, coordinator: "TadoDataUpdateCoordinator", zone_id: str,
        zone_name: str, zone_type: str, device: dict,
    ):
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._device_serial = device.get('shortSerialNo', 'unknown')
        self._device_type = device.get('deviceType', 'unknown')

        self._attr_name = "Battery"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_device_{self._device_serial}_battery"
        self._attr_icon = "mdi:battery"
        self._attr_available = True
        self._attr_native_value = _format_battery_state(device.get('batteryState', 'unknown'))
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, coordinator.home_id)

        # Extra attributes
        self._firmware = device.get('currentFwVersion')
        self._connection_state = (device.get('connectionState') or {}).get('value')
        self._connection_timestamp = (device.get('connectionState') or {}).get('timestamp')
        self._recommendation: str = ""  # Actionable recommendation

    @property
    def icon(self):
        if self._attr_native_value == 'Low':
            return "mdi:battery-low"
        if self._attr_native_value == 'Critical':
            return "mdi:battery-alert"
        return "mdi:battery"

    @property
    def extra_state_attributes(self):
        return {
            "device_serial": self._device_serial,
            "device_type": self._device_type,
            "firmware_version": self._firmware,
            "connection_state": _format_connection_state_attr(self._connection_state),
            "connection_timestamp": self._connection_timestamp,
            "recommendation": self._recommendation,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self):
        try:
            zones_info = (self.coordinator.data or {}).get("zones_info")
            if zones_info:
                for zone in zones_info:
                    for device in zone.get('devices', []):
                        if device.get('shortSerialNo') == self._device_serial:
                            raw_battery = device.get('batteryState', 'unknown')
                            self._attr_native_value = _format_battery_state(raw_battery)
                            self._firmware = device.get('currentFwVersion')
                            conn = device.get('connectionState') or {}
                            self._connection_state = conn.get('value')
                            self._connection_timestamp = conn.get('timestamp')

                            self._recommendation = calculate_battery_recommendation(
                                battery_state=raw_battery,
                                zone_name=self._zone_name,
                                device_type=self._device_type
                            )

                            self._attr_available = True
                            return
            self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoDeviceConnectionSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Device connection state sensor."""

    def __init__(
        self, coordinator: "TadoDataUpdateCoordinator", zone_id: str,
        zone_name: str, zone_type: str, device: dict,
    ):
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._device_serial = device.get('shortSerialNo', 'unknown')
        self._device_type = device.get('deviceType', 'unknown')
        self._zone_name = zone_name
        self._zone_type = zone_type

        self._attr_name = "Connection"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_device_{self._device_serial}_connection"
        self._attr_icon = "mdi:wifi"
        self._attr_available = True
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, coordinator.home_id)

        conn = device.get('connectionState') or {}
        self._attr_native_value = _format_connection_state(conn.get('value'))
        self._connection_timestamp = conn.get('timestamp')
        self._firmware = device.get('currentFwVersion')
        self._recommendation: str = ""

    @property
    def icon(self):
        if self._attr_native_value == "Online":
            return "mdi:wifi"
        return "mdi:wifi-off"

    @property
    def extra_state_attributes(self):
        return {
            "device_serial": self._device_serial,
            "device_type": self._device_type,
            "firmware_version": self._firmware,
            "last_seen": self._connection_timestamp,
            "recommendation": self._recommendation,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self):
        try:
            zones_info = (self.coordinator.data or {}).get("zones_info")
            if zones_info:
                for zone in zones_info:
                    for device in zone.get('devices', []):
                        if device.get('shortSerialNo') == self._device_serial:
                            conn = device.get('connectionState') or {}
                            self._attr_native_value = _format_connection_state(conn.get('value'))
                            self._connection_timestamp = conn.get('timestamp')
                            self._firmware = device.get('currentFwVersion')

                            offline_minutes = None
                            if self._connection_timestamp and self._attr_native_value == "Offline":
                                try:
                                    from datetime import datetime, timezone
                                    last_seen_dt = datetime.fromisoformat(
                                        self._connection_timestamp.replace('Z', '+00:00')
                                    )
                                    now_utc = datetime.now(timezone.utc)
                                    offline_minutes = int((now_utc - last_seen_dt).total_seconds() / 60)
                                except Exception:
                                    pass

                            self._recommendation = calculate_connection_recommendation(
                                connection_state=self._attr_native_value,
                                zone_name=self._zone_name,
                                last_seen=self._connection_timestamp,
                                offline_minutes=offline_minutes
                            )

                            self._attr_available = True
                            return
            self._attr_available = False
        except Exception:
            self._attr_available = False
