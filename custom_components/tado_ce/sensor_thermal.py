"""Tado CE Thermal Analysis Sensors — inertia, heating rate, preheat time, etc."""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device_manager import get_zone_device_info
from .insights import calculate_confidence_recommendation

_LOGGER = logging.getLogger(__name__)

class TadoThermalInertiaSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    """Sensor for thermal inertia time (delay before temperature rises)."""

    def __init__(self, home_id: str, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._home_id = home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Thermal Inertia"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_thermal_inertia"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:timer-sand"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("inertia_time")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("inertia_time") is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "confidence_score": zone_data.get("confidence_score", 0.0),
        }


class TadoHeatingRateSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    """Sensor for heating rate (°C per minute)."""

    def __init__(self, home_id: str, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._home_id = home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Heating Rate"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_heating_rate"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._attr_native_unit_of_measurement = "°C/min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:trending-up"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("heating_rate")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("heating_rate") is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "confidence_score": zone_data.get("confidence_score", 0.0),
        }


class TadoPreheatTimeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    """Sensor for estimated preheat time to reach target temperature."""

    def __init__(self, home_id: str, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._home_id = home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Preheat Time"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_preheat_time"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._attr_native_unit_of_measurement = "min"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:clock-fast"
        self._current_temp: Optional[float] = None
        self._target_temp: Optional[float] = None

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        # Get current and target temps from cached zone state (avoids blocking I/O)
        zone_state = self.coordinator.get_zone_state(self._zone_id)
        if not zone_state:
            return None

        current_temp = zone_state.get("current_temp")
        target_temp = zone_state.get("target_temp")

        if current_temp is None or target_temp is None:
            return None

        # Store for attributes
        self._current_temp = current_temp
        self._target_temp = target_temp

        # Get estimate from coordinator
        estimate = self.coordinator.estimate_preheat_time(
            self._zone_id, current_temp, target_temp
        )
        return estimate

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        zone_state = self.coordinator.get_zone_state(self._zone_id)
        # Need both: analysis data (heating_rate) AND current zone state (temps)
        return (
            zone_data is not None
            and zone_data.get("heating_rate") is not None
            and zone_state is not None
        )

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "current_temp": self._current_temp,
            "target_temp": self._target_temp,
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "confidence_score": zone_data.get("confidence_score", 0.0),
        }


class TadoConfidenceSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    """Sensor for confidence score of preheat estimates (0-100%)."""

    def __init__(self, home_id: str, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._home_id = home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Confidence"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_confidence"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chart-line"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        # Convert 0.0-1.0 to 0-100%
        confidence = zone_data.get("confidence_score")
        if confidence is not None:
            return round(confidence * 100, 1)
        return None

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        cycle_count = zone_data.get("cycle_count", 0)
        completed_count = zone_data.get("completed_count", 0)
        # Calculate SMART actionable recommendation
        confidence = zone_data.get("confidence_score")
        confidence_pct = round(confidence * 100, 1) if confidence is not None else None
        recommendation = calculate_confidence_recommendation(
            confidence_percent=confidence_pct,
            zone_name=self._zone_name,
            cycle_count=cycle_count,
            completed_count=completed_count
        )
        return {
            "cycle_count": cycle_count,
            "completed_count": completed_count,
            "recommendation": recommendation,  # Actionable recommendation
        }


class TadoHeatingAccelerationSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    """Sensor for heating acceleration (second-order analysis).

    Measures how quickly the heating rate increases after heating starts.
    Higher acceleration = faster response system.
    """

    def __init__(self, home_id: str, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._home_id = home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Heat Accel"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_heat_accel"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._attr_native_unit_of_measurement = "°C/h²"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:chart-bell-curve-cumulative"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("acceleration")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("acceleration") is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
        }


class TadoApproachFactorSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    """Sensor for approach deceleration factor (second-order analysis).

    Measures how much the heating rate decreases as temperature
    approaches the setpoint. Used to predict overshoot.

    Factor interpretation:
    - 100%: No deceleration, will likely overshoot
    - 50%: 50% deceleration, controlled approach
    - 0%: Complete stop before setpoint (rare)
    """

    def __init__(self, home_id: str, coordinator, zone_id: str, zone_name: str, zone_type: str):
        """Initialize sensor with coordinator."""
        super().__init__(coordinator)
        self._home_id = home_id
        self._zone_id = zone_id
        self._zone_name = zone_name
        self._zone_type = zone_type
        self._attr_name = "[CE] Approach Factor"
        self._attr_unique_id = f"tado_ce_{home_id}_zone_{zone_id}_approach_factor"
        self._attr_device_info = get_zone_device_info(zone_id, zone_name, zone_type, home_id)
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:target"

    @property
    def native_value(self):
        """Return sensor value from coordinator data."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return None
        return zone_data.get("approach_factor")

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        return zone_data is not None and zone_data.get("approach_factor") is not None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        zone_data = self.coordinator.get_zone_data(self._zone_id)
        if not zone_data:
            return {}
        return {
            "cycle_count": zone_data.get("cycle_count", 0),
            "completed_count": zone_data.get("completed_count", 0),
            "overshoot_estimate": zone_data.get("overshoot_estimate"),
        }

