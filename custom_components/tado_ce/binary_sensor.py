"""Tado CE Binary Sensors."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_hub_device_info, get_zone_device_info
from .format_helpers import (
    format_confidence as _format_confidence,
)
from .format_helpers import (
    format_data_source as _format_data_source,
)
from .format_helpers import (
    format_tado_mode as _format_tado_mode,
)
from .format_helpers import (
    format_zone_type as _format_zone_type,
)
from .insights import TemperatureReading, detect_window_predicted

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
):
    """Set up Tado CE binary sensors from a config entry."""
    _LOGGER.debug("Tado CE binary_sensor: Setting up...")
    coordinator: TadoDataUpdateCoordinator = entry.runtime_data
    data_loader = coordinator.data_loader
    home_id = coordinator.home_id
    config_manager = coordinator.config_manager
    zones_info = await hass.async_add_executor_job(data_loader.load_zones_info_file)

    # Check if Smart Comfort is enabled (required for Preheat Now sensor)
    smart_comfort_enabled = config_manager.get_smart_comfort_enabled()

    sensors = []

    # Home/Away sensor (global)
    sensors.append(TadoHomeSensor(coordinator))

    # Open Window sensors (per zone that supports it)
    if zones_info:
        for zone in zones_info:
            zone_id = str(zone.get('id'))
            zone_name = zone.get('name', f"Zone {zone_id}")
            zone_type = zone.get('type')

            # Only add open window for heating zones that support it
            if zone_type == 'HEATING':
                owd = zone.get('openWindowDetection') or {}
                if owd.get('supported', False):
                    sensors.append(TadoOpenWindowSensor(coordinator, zone_id, zone_name, zone_type, home_id))

                # Add Preheat Now sensor if Smart Comfort is enabled
                if smart_comfort_enabled:
                    sensors.append(TadoPreheatNowSensor(coordinator, zone_id, zone_name, zone_type, home_id))

            # Window Predicted sensor for all climate zones (HEATING and AIR_CONDITIONING)
            if zone_type in ('HEATING', 'AIR_CONDITIONING'):
                sensors.append(TadoWindowPredictedSensor(coordinator, zone_id, zone_name, zone_type, home_id))



    async_add_entities(sensors, False)  # Don't update before add - self.hass not set yet
    _LOGGER.debug("Tado CE binary sensors loaded: %s", len(sensors))


class TadoHomeSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    _attr_has_entity_name = True

    """Binary sensor for Tado Home/Away status.

    Reads from home_state.json (source of truth for presence) instead of
    zones.json tadoMode. Falls back to zones.json if home_state is not
    available (e.g., home_state_sync_enabled=false).
    """

    def __init__(self, coordinator: TadoDataUpdateCoordinator):
        super().__init__(coordinator)
        self._attr_name = "[CE] Home"
        self.entity_id = "binary_sensor.tado_ce_home"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_home"
        self._attr_device_class = BinarySensorDeviceClass.PRESENCE
        self._attr_available = False
        self._attr_is_on = None
        # Use hub device info for global entities
        self._attr_device_info = get_hub_device_info(coordinator.home_id)
        self._tado_mode = None
        self._presence_locked = None  # Track if presence is locked (manual override)
        self._data_source = None  # Track which data source is being used

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            "tado_mode": _format_tado_mode(self._tado_mode),
            "presence_locked": self._presence_locked,
            "data_source": _format_data_source(self._data_source),
        }

    @callback
    def update(self):
        """Update from home_state.json (primary) or zones.json (fallback).

        Changed to read from home_state.json as source of truth.
        Falls back to zones.json tadoMode if home_state is not available.
        """
        try:
            # Use coordinator cached data (async-loaded, no file I/O)
            coord_data = self.coordinator.data or {}

            # Primary: Read from home_state (source of truth for presence)
            home_state = coord_data.get("home_state")
            if home_state:
                presence = home_state.get('presence', 'HOME')
                self._presence_locked = home_state.get('presenceLocked', False)
                self._attr_is_on = presence == 'HOME'
                self._tado_mode = presence  # Keep tado_mode attribute for compatibility
                self._data_source = "home_state"
                self._attr_available = True
                return

            # Fallback: Read from zones tadoMode
            # This is used when home_state_sync_enabled=false
            data = coord_data.get("zones")
            if data:
                zone_states = data.get('zoneStates') or {}
                for zone_id, zone_data in zone_states.items():
                    self._tado_mode = zone_data.get('tadoMode')
                    if self._tado_mode:
                        self._attr_is_on = self._tado_mode == 'HOME'
                        self._presence_locked = zone_data.get('geolocationOverride', False)
                        self._data_source = "zones"
                        self._attr_available = True
                        return

            self._attr_available = False
        except Exception as e:
            _LOGGER.warning("TadoHomeSensor update failed: %s", e)
            self._attr_available = False


class TadoOpenWindowSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    _attr_has_entity_name = True

    """Binary sensor for Tado Open Window detection."""

    def __init__(self, coordinator: TadoDataUpdateCoordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING", home_id: str = ""):
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "Window"
        # Use zone_id for unique_id to maintain entity_id stability across zone name changes
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_open_window"
        self._attr_device_class = BinarySensorDeviceClass.WINDOW
        self._attr_available = False
        self._attr_is_on = None
        # Use zone device info instead of hub device info
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._detected_time = None
        self._expiry_time = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            "detected_time": self._detected_time,
            "expiry_time": self._expiry_time,
        }

    @callback
    def update(self):
        try:
            # Use coordinator cached zones data (async-loaded, no file I/O)
            coord_data = self.coordinator.data or {}
            data = coord_data.get("zones")
            if data:
                # Use 'or {}' pattern for null safety
                zone_states = data.get('zoneStates') or {}
                zone_data = zone_states.get(self._zone_id)

                if not zone_data:
                    self._attr_available = False
                    return

                open_window = zone_data.get('openWindow')
                open_window_detected = zone_data.get('openWindowDetected', False)

                if open_window:
                    self._attr_is_on = True
                    self._detected_time = open_window.get('detectedTime')
                    self._expiry_time = open_window.get('expiryTime')
                elif open_window_detected:
                    self._attr_is_on = True
                    self._detected_time = None
                    self._expiry_time = None
                else:
                    self._attr_is_on = False
                    self._detected_time = None
                    self._expiry_time = None

                self._attr_available = True
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoPreheatNowSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    _attr_has_entity_name = True

    """Binary sensor indicating when to start preheating.

    Turns ON when current time >= recommended preheat start time.
    Uses data from TadoPreheatAdvisorSensor to determine timing.

    UFH buffer is already applied in TadoPreheatAdvisorSensor,
    so this sensor just reads the adjusted time directly.
    """

    def __init__(self, coordinator: TadoDataUpdateCoordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING", home_id: str = ""):
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Preheat Now"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_preheat_now"
        self._attr_device_class = BinarySensorDeviceClass.HEAT
        self._attr_available = False
        self._attr_is_on = None
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)

        # Attributes for debugging/display
        self._recommended_start = None
        self._target_time = None
        self._target_temp = None
        self._current_temp = None
        self._duration_minutes = None
        self._confidence = "unknown"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            "recommended_start": self._recommended_start,
            "target_time": self._target_time,
            "target_temperature": self._target_temp,
            "current_temperature": self._current_temp,
            "duration_minutes": self._duration_minutes,
            "confidence": _format_confidence(self._confidence),
            "zone_type": _format_zone_type(self._zone_type),
        }

    @property
    def icon(self):
        """Dynamic icon based on state."""
        if self._attr_is_on:
            return "mdi:radiator"
        return "mdi:radiator-off"

    @callback
    def update(self):
        """Update preheat now status.

        Logic:
        1. Get preheat advisor data for this zone (already includes UFH buffer)
        2. If recommended start time exists and is valid
        3. Turn ON if current time >= recommended start time
        """
        try:
            from datetime import datetime

            if not self.hass:
                self._attr_available = False
                return

            # Find the preheat advisor sensor for this zone
            # Try different entity_id formats
            zone_slug = self._zone_name.lower().replace(' ', '_')
            preheat_advisor_id = f"sensor.{zone_slug}_preheat_advisor"
            preheat_state = self.hass.states.get(preheat_advisor_id)

            if not preheat_state:
                # Try with zone name as-is
                preheat_advisor_id = f"sensor.{self._zone_name}_preheat_advisor"
                preheat_state = self.hass.states.get(preheat_advisor_id)

            # Copy attributes from preheat advisor
            if preheat_state:
                self._target_time = preheat_state.attributes.get('target_time')
                self._target_temp = preheat_state.attributes.get('target_temperature')
                self._current_temp = preheat_state.attributes.get('current_temperature')
                self._duration_minutes = preheat_state.attributes.get('duration_minutes')
                self._confidence = preheat_state.attributes.get('confidence', 'unknown')

            # Check for non-actionable states
            non_actionable_states = (
                'unavailable', 'unknown', 'No schedule',
                'Heating OFF', 'Ready', 'Insufficient data',
            )
            if not preheat_state or preheat_state.state in non_actionable_states:
                self._attr_is_on = False
                self._attr_available = True
                self._recommended_start = None
                return

            # Parse recommended start time (format: "HH:MM")
            # Note: UFH buffer is already applied in TadoPreheatAdvisorSensor
            try:
                recommended_str = preheat_state.state
                now = datetime.now()
                recommended_time = datetime.strptime(recommended_str, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )

                self._recommended_start = recommended_str

                # Check if it's time to preheat
                self._attr_is_on = now >= recommended_time
                self._attr_available = True

            except ValueError:
                # Invalid time format
                self._attr_is_on = False
                self._attr_available = True
                self._recommended_start = None

        except Exception as e:
            _LOGGER.debug("Failed to update preheat now for zone %s: %s", self._zone_id, e)
            self._attr_available = False


class TadoWindowPredictedSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    _attr_has_entity_name = True

    """Binary sensor for early open window detection.

    Detects possible open windows using local temperature analysis,
    providing early warning before Tado's cloud detection triggers.

    This is a PREDICTIVE sensor - it does NOT replace Tado's confirmed
    Window binary sensor (binary_sensor.{zone}_window).
    """

    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, coordinator: TadoDataUpdateCoordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING", home_id: str = ""):
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Window Predicted"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_window_predicted"
        self._attr_available = False
        self._attr_is_on = None
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)

        # Detection state
        self._confidence: str = "none"
        self._temp_drop: float = 0.0
        self._time_window: int = 5
        self._recommendation: str = ""
        self._anomaly_readings: int = 0

        # Rolling temperature history for consecutive-reading comparison
        self._temp_history: deque = deque(maxlen=10)
        self._last_reading_time: datetime = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        return {
            "confidence": _format_confidence(self._confidence),
            "temp_drop": self._temp_drop,
            "time_window_minutes": self._time_window,
            "recommendation": self._recommendation,
            "zone_type": _format_zone_type(self._zone_type),
            "readings_count": len(self._temp_history),
            "anomaly_readings": self._anomaly_readings,
        }

    @property
    def icon(self):
        """Dynamic icon based on state."""
        if self._attr_is_on:
            return "mdi:window-open-variant"
        return "mdi:window-closed-variant"

    @callback
    def update(self):
        """Update window predicted detection via heating anomaly algorithm.

        Logic:
        1. Get current temperature and humidity from zone data
        2. Add to rolling history
        3. Determine HVAC state and mode (heating vs cooling)
        4. Run anomaly detection — heating active but temp dropping = open window
        """
        try:
            # Use coordinator cached zones data (async-loaded, no file I/O)
            coord_data = self.coordinator.data or {}
            data = coord_data.get("zones")
            if not data:
                self._attr_available = False
                return

            zone_states = data.get('zoneStates') or {}
            zone_data = zone_states.get(self._zone_id)

            if not zone_data:
                self._attr_available = False
                return

            # Get current temperature and humidity
            sensor_data = zone_data.get('sensorDataPoints') or {}
            temp_data = sensor_data.get('insideTemperature') or {}
            humidity_data = sensor_data.get('humidity') or {}

            current_temp = temp_data.get('celsius')
            current_humidity = humidity_data.get('percentage')

            if current_temp is None:
                self._attr_available = False
                return

            # Add reading to history (throttle to avoid duplicates)
            now = datetime.now()
            if self._last_reading_time is None or (now - self._last_reading_time).total_seconds() >= 25:
                reading = TemperatureReading(
                    temperature=current_temp,
                    humidity=current_humidity,
                    timestamp=now
                )
                self._temp_history.append(reading)
                self._last_reading_time = now

            # Determine HVAC state and mode
            activity_data = zone_data.get('activityDataPoints') or {}
            heating_power = activity_data.get('heatingPower') or {}
            ac_power = activity_data.get('acPower')

            heating_percentage = heating_power.get('percentage', 0)
            ac_on = ac_power is not None and ac_power.get('value') == 'ON'
            hvac_active = heating_percentage > 0 or ac_on

            # Determine hvac_mode for anomaly direction
            if ac_on:
                hvac_mode = "cooling"
            else:
                hvac_mode = "heating"

            # Run heating/cooling anomaly detection
            result = detect_window_predicted(
                readings=list(self._temp_history),
                hvac_active=hvac_active,
                zone_name=self._zone_name,
                time_window_minutes=self._time_window,
                hvac_mode=hvac_mode,
            )

            self._attr_is_on = result.detected
            self._confidence = result.confidence
            self._temp_drop = result.temp_drop
            self._recommendation = result.recommendation
            self._anomaly_readings = result.anomaly_readings
            self._attr_available = True

        except Exception as e:
            _LOGGER.debug("Failed to update window predicted for zone %s: %s", self._zone_id, e)
            self._attr_available = False
