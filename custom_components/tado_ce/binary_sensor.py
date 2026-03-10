"""Tado CE Binary Sensors — window open detection, preheat now, connectivity."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
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
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import TadoConfigEntry, TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tado CE binary sensors from a config entry."""
    _LOGGER.debug("Tado CE binary_sensor: Setting up...")
    coordinator = entry.runtime_data
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
            zone_id = str(zone.get("id"))
            zone_name = zone.get("name", f"Zone {zone_id}")
            zone_type = zone.get("type")

            # Only add open window for heating zones that support it
            if zone_type == "HEATING":
                owd = zone.get("openWindowDetection") or {}
                if owd.get("supported", False):
                    sensors.append(TadoOpenWindowSensor(coordinator, zone_id, zone_name, zone_type, home_id))  # type: ignore[arg-type]

                # Add Preheat Now sensor if Smart Comfort is enabled
                if smart_comfort_enabled:
                    sensors.append(TadoPreheatNowSensor(coordinator, zone_id, zone_name, zone_type, home_id))  # type: ignore[arg-type]

            # Window Predicted sensor for all climate zones (HEATING and AIR_CONDITIONING)
            if zone_type in ("HEATING", "AIR_CONDITIONING"):
                sensors.append(TadoWindowPredictedSensor(coordinator, zone_id, zone_name, zone_type, home_id))  # type: ignore[arg-type]

    async_add_entities(sensors, False)  # Don't update before add - self.hass not set yet
    _LOGGER.debug("Tado CE binary sensors loaded: %s", len(sensors))


class TadoHomeSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    """Represent a Tado home-level binary sensor."""

    _attr_has_entity_name = True

    """Binary sensor for Tado Home/Away status.

    Reads from home_state.json (source of truth for presence) instead of
    zones.json tadoMode. Falls back to zones.json if home_state is not
    available (e.g., home_state_sync_enabled=false).
    """

    def __init__(self, coordinator: TadoDataUpdateCoordinator) -> None:
        """Initialize the Home Sensor."""
        super().__init__(coordinator)
        self._attr_translation_key = "home"
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
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "tado_mode": _format_tado_mode(self._tado_mode),  # type: ignore[arg-type]
            "presence_locked": self._presence_locked,
            "data_source": _format_data_source(self._data_source),  # type: ignore[arg-type]
        }

    @callback
    def update(self) -> None:
        """Update from home_state.json (primary) or zones.json (fallback).

        Changed to read from home_state.json as source of truth.
        Falls back to zones.json tadoMode if home_state is not available.
        """
        try:
            coord_data = self.coordinator.data or {}

            # Primary: Read from home_state (source of truth for presence)
            home_state = coord_data.get("home_state")
            if home_state:
                presence = home_state.get("presence", "HOME")
                self._presence_locked = home_state.get("presenceLocked", False)
                self._attr_is_on = presence == "HOME"
                self._tado_mode = presence  # Keep tado_mode attribute for compatibility
                self._data_source = "home_state"  # type: ignore[assignment]
                self._attr_available = True
                return

            # Fallback: Read from zones tadoMode
            # This is used when home_state_sync_enabled=false
            data = coord_data.get("zones")
            if data:
                zone_states = data.get("zoneStates") or {}
                for zone_data in zone_states.values():
                    self._tado_mode = zone_data.get("tadoMode")
                    if self._tado_mode:
                        self._attr_is_on = self._tado_mode == "HOME"
                        self._presence_locked = zone_data.get("geolocationOverride", False)
                        self._data_source = "zones"
                        self._attr_available = True
                        return

            self._attr_available = False
        except Exception as e:
            _LOGGER.warning("TadoHomeSensor update failed: %s", e)
            self._attr_available = False


class TadoOpenWindowSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    """Represent a Tado open window detection binary sensor."""

    _attr_has_entity_name = True

    """Binary sensor for Tado Open Window detection."""

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        zone_type: str = "HEATING",
        home_id: str = "",
    ) -> None:
        """Initialize the Open Window Sensor."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_translation_key = "window"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_open_window"
        self._attr_device_class = BinarySensorDeviceClass.WINDOW
        self._attr_available = False
        self._attr_is_on = None
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._detected_time = None
        self._expiry_time = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "detected_time": self._detected_time,
            "expiry_time": self._expiry_time,
        }

    @callback
    def update(self) -> None:
        """Update entity state from coordinator data."""
        try:
            coord_data = self.coordinator.data or {}
            data = coord_data.get("zones")
            if data:
                # Use 'or {}' pattern for null safety
                zone_states = data.get("zoneStates") or {}
                zone_data = zone_states.get(self._zone_id)

                if not zone_data:
                    self._attr_available = False
                    return

                open_window = zone_data.get("openWindow")
                open_window_detected = zone_data.get("openWindowDetected", False)

                if open_window:
                    self._attr_is_on = True
                    self._detected_time = open_window.get("detectedTime")
                    self._expiry_time = open_window.get("expiryTime")
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
            _LOGGER.debug("Failed to update open window sensor for zone %s", self._zone_id)
            self._attr_available = False


class TadoPreheatNowSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    """Represent a Tado preheat-active binary sensor."""

    _attr_has_entity_name = True

    """Binary sensor indicating when to start preheating.

    Turns ON when current time >= recommended preheat start time.
    Uses data from TadoPreheatAdvisorSensor to determine timing.

    UFH buffer is already applied in TadoPreheatAdvisorSensor,
    so this sensor just reads the adjusted time directly.
    """

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        zone_type: str = "HEATING",
        home_id: str = "",
    ) -> None:
        """Initialize the Preheat Now Sensor."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_translation_key = "preheat_now"
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
        self._is_tomorrow: bool = False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
        return {
            "recommended_start": self._recommended_start,
            "target_time": self._target_time,
            "target_temperature": self._target_temp,
            "current_temperature": self._current_temp,
            "duration_minutes": self._duration_minutes,
            "confidence": _format_confidence(self._confidence),
            "is_tomorrow": self._is_tomorrow,
            "zone_type": _format_zone_type(self._zone_type),
        }

    @property
    def icon(self) -> str | None:
        """Dynamic icon based on state."""
        if self._attr_is_on:
            return "mdi:radiator"
        return "mdi:radiator-off"

    @callback
    def update(self) -> None:
        """Update preheat now status.

        Logic:
        1. Get preheat advisor data from coordinator.entity_data (no hass.states.get)
        2. If recommended start time exists and is valid
        3. Turn ON if current time >= recommended start time
        """
        try:
            from datetime import datetime

            if not self.hass:
                self._attr_available = False
                return

            # Read preheat advisor data from coordinator (published by TadoPreheatAdvisorSensor)
            preheat_data = self.coordinator.get_entity_data(self._zone_id, "preheat_advisor")

            # Copy attributes from preheat advisor data
            if preheat_data:
                self._target_time = preheat_data.get("target_time")
                self._target_temp = preheat_data.get("target_temperature")
                self._current_temp = preheat_data.get("current_temperature")
                self._duration_minutes = preheat_data.get("duration_minutes")
                self._confidence = preheat_data.get("confidence", "unknown")
                self._is_tomorrow = preheat_data.get("is_tomorrow", False)

            # Check for non-actionable states
            non_actionable_states = (
                "unavailable",
                "unknown",
                "No schedule",
                "Heating OFF",
                "Ready",
                "Insufficient data",
                None,
            )
            preheat_state_val = preheat_data.get("state") if preheat_data else None
            if not preheat_data or preheat_state_val in non_actionable_states:
                self._attr_is_on = False
                self._attr_available = True
                self._recommended_start = None
                return

            # If preheat is for a future day, never trigger
            if self._is_tomorrow:
                self._attr_is_on = False
                self._attr_available = True
                self._recommended_start = preheat_state_val
                return

            # Parse recommended start time (format: "HH:MM")
            # Note: UFH buffer is already applied in TadoPreheatAdvisorSensor
            try:
                recommended_str = preheat_state_val
                from homeassistant.util import dt as dt_util

                now = dt_util.now()
                recommended_time = datetime.strptime(recommended_str, "%H:%M").replace(  # type: ignore[arg-type]
                    year=now.year,
                    month=now.month,
                    day=now.day,
                    tzinfo=now.tzinfo,
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
        finally:
            # Publish computed state to coordinator for cross-component access
            # (used by AdaptivePreheatManager initial state check)
            self.coordinator.publish_entity_data(
                self._zone_id,
                "preheat_now",
                {
                    "state": "on" if self._attr_is_on else "off",
                    "recommended_start": self._recommended_start,
                },
            )


class TadoWindowPredictedSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], BinarySensorEntity):
    """Represent a Tado predicted window-open binary sensor."""

    _attr_has_entity_name = True

    """Binary sensor for early open window detection.

    Detects possible open windows using local temperature analysis,
    providing early warning before Tado's cloud detection triggers.

    This is a PREDICTIVE sensor - it does NOT replace Tado's confirmed
    Window binary sensor (binary_sensor.{zone}_window).
    """

    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(
        self,
        coordinator: TadoDataUpdateCoordinator,
        zone_id: str,
        zone_name: str,
        zone_type: str = "HEATING",
        home_id: str = "",
    ) -> None:
        """Initialize the Window Predicted Sensor."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_translation_key = "window_predicted"
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
        self._temp_history: deque = deque(maxlen=10)  # type: ignore[type-arg]
        self._last_reading_time: datetime = None  # type: ignore[assignment]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra state attributes."""
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
    def icon(self) -> str | None:
        """Dynamic icon based on state."""
        if self._attr_is_on:
            return "mdi:window-open-variant"
        return "mdi:window-closed-variant"

    @callback
    def update(self) -> None:
        """Update window predicted detection via heating anomaly algorithm.

        Logic:
        1. Get current temperature and humidity from zone data
        2. Add to rolling history
        3. Determine HVAC state and mode (heating vs cooling)
        4. Run anomaly detection — heating active but temp dropping = open window
        """
        try:
            coord_data = self.coordinator.data or {}
            data = coord_data.get("zones")
            if not data:
                self._attr_available = False
                return

            zone_states = data.get("zoneStates") or {}
            zone_data = zone_states.get(self._zone_id)

            if not zone_data:
                self._attr_available = False
                return

            sensor_data = zone_data.get("sensorDataPoints") or {}
            temp_data = sensor_data.get("insideTemperature") or {}
            humidity_data = sensor_data.get("humidity") or {}

            current_temp = temp_data.get("celsius")
            current_humidity = humidity_data.get("percentage")

            if current_temp is None:
                self._attr_available = False
                return

            # Add reading to history (throttle to avoid duplicates)
            now = datetime.now(UTC)
            if self._last_reading_time is None or (now - self._last_reading_time).total_seconds() >= 25:
                reading = TemperatureReading(
                    temperature=current_temp,
                    humidity=current_humidity,
                    timestamp=now,
                )
                self._temp_history.append(reading)
                self._last_reading_time = now

            # Determine HVAC state and mode
            activity_data = zone_data.get("activityDataPoints") or {}
            heating_power = activity_data.get("heatingPower") or {}
            ac_power = activity_data.get("acPower")

            heating_percentage = heating_power.get("percentage", 0)
            ac_on = ac_power is not None and ac_power.get("value") == "ON"
            hvac_active = heating_percentage > 0 or ac_on

            # Determine hvac_mode for anomaly direction
            hvac_mode = "cooling" if ac_on else "heating"

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

            # Publish computed data to coordinator for cross-component access
            self.coordinator.publish_entity_data(
                self._zone_id,
                "window_predicted",
                {
                    "state": "on" if result.detected else "off",
                    "recommendation": result.recommendation,
                },
            )

        except Exception as e:
            _LOGGER.debug("Failed to update window predicted for zone %s: %s", self._zone_id, e)
            self._attr_available = False
