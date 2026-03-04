"""Tado CE Smart Comfort Sensors — schedule deviation, preheat advisor, etc."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorStateClass
from homeassistant.core import callback

from .format_helpers import (
    format_comfort_model as _format_comfort_model,
)
from .format_helpers import (
    format_confidence as _format_confidence,
)
from .format_helpers import (
    format_zone_type as _format_zone_type,
)
from .insights import (
    calculate_historical_deviation_recommendation,
)
from .sensor_helpers import get_outdoor_temperature as _get_outdoor_temp
from .sensor_zone import TadoZoneSensor

_LOGGER = logging.getLogger(__name__)

class TadoScheduleDeviationSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Historical temperature comparison sensor.

    Compares current temperature to the 7-day average at the same time of day.
    Helps identify unusual temperature patterns.

    State: Difference from historical average (e.g., "+1.2" or "-0.8")
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Schedule Deviation"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_schedule_deviation"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_icon = "mdi:chart-timeline-variant"
        self._attr_state_class = SensorStateClass.MEASUREMENT

        # Attributes
        self._current_temp: float | None = None
        self._historical_avg: float | None = None
        self._sample_count: int = 0
        self._summary: str = ""
        self._recommendation: str = ""  # Actionable recommendation

    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "historical_average": self._historical_avg,
            "sample_count": self._sample_count,
            "summary": self._summary,
            "zone_type": _format_zone_type(self._zone_type),
            "recommendation": self._recommendation,  # Actionable recommendation
        }

    @property
    def icon(self):
        """Dynamic icon based on comparison."""
        if self._attr_native_value is None:
            return "mdi:chart-timeline-variant"
        elif self._attr_native_value > 0.5:
            return "mdi:thermometer-chevron-up"
        elif self._attr_native_value < -0.5:
            return "mdi:thermometer-chevron-down"
        return "mdi:thermometer-check"

    @callback
    def update(self):
        """Update historical comparison from SmartComfortManager."""
        try:
            manager = self.coordinator.smart_comfort_manager if self.hass else None

            if not manager or not manager.is_enabled:
                self._attr_available = False
                return

            # Get current temperature from zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return

            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')

            if self._current_temp is None:
                self._attr_available = False
                return

            # Get historical comparison
            comparison = manager.get_historical_comparison(
                self._zone_id,
                self._current_temp
            )

            if comparison is None:
                self._attr_native_value = None
                self._attr_available = False
                self._historical_avg = None
                self._sample_count = 0
                self._summary = "Insufficient data"
                return

            self._attr_native_value = comparison.difference
            self._historical_avg = comparison.historical_avg
            self._sample_count = comparison.sample_count
            self._summary = comparison.to_summary()

            # Calculate SMART actionable recommendation
            self._recommendation = calculate_historical_deviation_recommendation(
                deviation=comparison.difference,
                zone_name=self._zone_name,
                current_temp=self._current_temp,
                historical_avg=comparison.historical_avg,
                sample_count=comparison.sample_count
            )

            self._attr_available = True

        except Exception as e:
            _LOGGER.debug("Failed to update historical comparison for zone %s: %s", self._zone_id, e)
            self._attr_available = False


class TadoNextScheduleTimeSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Next schedule time sensor.

    Shows when the next scheduled temperature change will occur.

    State: Next schedule time (e.g., "17:00" or "Tomorrow 07:00")
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Next Schedule"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_next_schedule"
        self._attr_icon = "mdi:calendar-clock"

        # Attributes
        self._next_temp: float | None = None
        self._is_heating_on: bool = False
        self._is_tomorrow: bool = False
        self._minutes_until: int | None = None

    @property
    def extra_state_attributes(self):
        return {
            "next_temperature": self._next_temp,
            "is_heating_on": self._is_heating_on,
            "is_tomorrow": self._is_tomorrow,
            "minutes_until": self._minutes_until,
            "zone_type": _format_zone_type(self._zone_type),
        }

    @callback
    def update(self):
        """Update next schedule time from schedule data."""
        try:
            from datetime import datetime

            from .smart_comfort import get_next_schedule_change

            _dl = self.coordinator.data_loader
            next_block = get_next_schedule_change(self._zone_id, data_loader=_dl)

            if next_block is None:
                self._attr_native_value = "No schedule"
                self._attr_available = True
                self._next_temp = None
                self._is_heating_on = False
                self._is_tomorrow = False
                self._minutes_until = None
                return

            now = datetime.now()
            self._is_tomorrow = next_block.start_time.date() > now.date()
            self._is_heating_on = next_block.is_heating_on
            self._next_temp = next_block.target_temp

            # Calculate minutes until
            time_diff = next_block.start_time - now
            self._minutes_until = int(time_diff.total_seconds() / 60)

            # Format display value
            time_str = next_block.start_time.strftime("%H:%M")
            if self._is_tomorrow:
                self._attr_native_value = f"Tomorrow {time_str}"
            else:
                self._attr_native_value = time_str

            self._attr_available = True

        except Exception as e:
            _LOGGER.debug("Failed to update next schedule for zone %s: %s", self._zone_id, e)
            self._attr_available = False


class TadoNextScheduleTempSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Next schedule target temperature sensor.

    Shows the target temperature of the next scheduled block.

    State: Target temperature (°C) or "OFF"
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Next Sched Temp"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_next_sched_temp"
        # No unit_of_measurement so we can show "OFF" as state
        self._attr_icon = "mdi:thermometer-chevron-up"

        # Attributes
        self._schedule_time: str | None = None
        self._is_heating_on: bool = False
        self._current_temp: float | None = None
        self._temp_diff: float | None = None

    @property
    def extra_state_attributes(self):
        attrs = {
            "schedule_time": self._schedule_time,
            "is_heating_on": self._is_heating_on,
            "current_temperature": self._current_temp,
            "temperature_difference": self._temp_diff,
            "zone_type": _format_zone_type(self._zone_type),
        }
        # Add unit only when showing temperature
        if self._is_heating_on and isinstance(self._attr_native_value, (int, float)):
            attrs["unit_of_measurement"] = "°C"
        return attrs

    @property
    def icon(self):
        """Dynamic icon based on heating direction."""
        if self._temp_diff is not None:
            if self._temp_diff > 0:
                return "mdi:thermometer-chevron-up"
            elif self._temp_diff < 0:
                return "mdi:thermometer-chevron-down"
        if not self._is_heating_on:
            return "mdi:thermometer-off"
        return "mdi:thermometer"

    @callback
    def update(self):
        """Update next schedule temperature from schedule data."""
        try:
            from .smart_comfort import get_next_schedule_change

            _dl = self.coordinator.data_loader
            next_block = get_next_schedule_change(self._zone_id, data_loader=_dl)

            if next_block is None:
                self._attr_native_value = "No schedule"
                self._attr_available = True
                self._schedule_time = None
                self._is_heating_on = False
                self._current_temp = None
                self._temp_diff = None
                return

            self._is_heating_on = next_block.is_heating_on
            self._schedule_time = next_block.start_time.strftime("%H:%M")

            # Get current temperature
            zone_data = self._get_zone_data()
            if zone_data:
                sensor_data = zone_data.get('sensorDataPoints') or {}
                self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')

            if not next_block.is_heating_on or next_block.target_temp is None:
                # Heating OFF block - show "OFF" instead of unknown
                self._attr_native_value = "OFF"
                self._attr_available = True
                self._temp_diff = None
                return

            self._attr_native_value = next_block.target_temp

            # Calculate temperature difference
            if self._current_temp is not None:
                self._temp_diff = round(next_block.target_temp - self._current_temp, 1)
            else:
                self._temp_diff = None

            self._attr_available = True

        except Exception as e:
            _LOGGER.debug("Failed to update next schedule temp for zone %s: %s", self._zone_id, e)
            self._attr_available = False


class TadoPreheatAdvisorSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Preheat timing advisor sensor.

    Suggests optimal preheat start time based on historical heating rates.
    Uses the next scheduled target temperature from Tado schedule.

    State: Recommended start time (e.g., "06:15")
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Preheat Advisor"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_preheat_advisor"
        self._attr_icon = "mdi:clock-start"

        # Attributes
        self._current_temp: float | None = None
        self._target_temp: float | None = None
        self._target_time: str | None = None
        self._duration_minutes: int | None = None
        self._heating_rate: float | None = None
        self._confidence: str = "unknown"
        self._summary: str = ""

    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "target_temperature": self._target_temp,
            "target_time": self._target_time,
            "duration_minutes": self._duration_minutes,
            "heating_rate": self._heating_rate,
            "confidence": _format_confidence(self._confidence),
            "summary": self._summary,
            "zone_type": _format_zone_type(self._zone_type),
        }

    @property
    def icon(self):
        """Dynamic icon based on confidence."""
        if self._confidence == "high":
            return "mdi:clock-check"
        elif self._confidence == "medium":
            return "mdi:clock-alert"
        elif self._confidence == "low":
            return "mdi:clock-outline"
        elif self._confidence == "no_schedule":
            return "mdi:calendar-remove"
        elif self._confidence == "insufficient_data":
            return "mdi:database-off"
        return "mdi:clock-start"

    @callback
    def update(self):
        """Update preheat advice based on schedule and heating rate.

        Logic:
        1. Get next schedule block from schedules.json
        2. If next block has heating ON with target temp > current temp, calculate preheat time
        3. If already at or above target, show "Ready"
        4. If no schedule or heating OFF, show appropriate status
        """
        try:
            from .smart_comfort import get_next_schedule_change

            manager = self.coordinator.smart_comfort_manager if self.hass else None

            if not manager or not manager.is_enabled:
                self._attr_available = False
                return

            # Get current temperature from zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return

            sensor_data = zone_data.get('sensorDataPoints') or {}
            self._current_temp = (sensor_data.get('insideTemperature') or {}).get('celsius')

            if self._current_temp is None:
                self._attr_available = False
                return

            # Get next schedule change from schedules.json (per-entry data_loader)
            _dl = self.coordinator.data_loader
            next_block = get_next_schedule_change(self._zone_id, data_loader=_dl)

            if next_block is None:
                # No schedule data or no more blocks today
                self._attr_native_value = "No schedule"
                self._attr_available = True
                self._target_temp = None
                self._target_time = None
                self._duration_minutes = None
                self._heating_rate = None
                self._confidence = "no_schedule"
                self._summary = "No upcoming schedule changes today"
                return

            # Check if next block has heating ON
            if not next_block.is_heating_on or next_block.target_temp is None:
                # Next block is heating OFF
                self._attr_native_value = "Heating OFF"
                self._attr_available = True
                self._target_temp = None
                self._target_time = next_block.start_time.strftime("%H:%M")
                self._duration_minutes = 0
                self._heating_rate = None
                self._confidence = "high"
                self._summary = f"Heating turns OFF at {self._target_time}"
                return

            self._target_temp = next_block.target_temp
            self._target_time = next_block.start_time.strftime("%H:%M")

            # Check if already at or above target
            if self._current_temp >= self._target_temp:
                self._attr_native_value = "Ready"
                self._attr_available = True
                self._duration_minutes = 0
                self._heating_rate = None
                self._confidence = "high"
                self._summary = f"Already at {self._target_temp:.1f}°C (no preheat needed)"
                return

            # Need to preheat - calculate timing
            # Prioritize HeatingCycleCoordinator rate over SmartComfort rate
            # HeatingCycleCoordinator uses complete heating cycles for more accurate rate
            heating_cycle_coordinator = self.coordinator.heating_cycle_coordinator
            cycle_heating_rate = None
            cycle_confidence = None

            # Get UFH buffer from config_manager (only for selected zones)
            ufh_buffer = 0
            config_manager = self.coordinator.config_manager
            if config_manager:
                ufh_buffer_global = config_manager.get_ufh_buffer_minutes()
                ufh_zones = config_manager.get_ufh_zones()
                # Apply buffer only if: buffer > 0 AND (no zones selected OR this zone is selected)
                if ufh_buffer_global > 0:
                    if not ufh_zones or self._zone_id in ufh_zones:
                        ufh_buffer = ufh_buffer_global

            if heating_cycle_coordinator:
                zone_data_cycle = heating_cycle_coordinator.get_zone_data(self._zone_id)
                if zone_data_cycle and zone_data_cycle.get("heating_rate") is not None:
                    # HeatingCycleCoordinator rate is in °C/min, convert to °C/h for consistency
                    cycle_heating_rate = zone_data_cycle.get("heating_rate") * 60
                    cycle_count = zone_data_cycle.get("cycle_count", 0)
                    # Determine confidence based on cycle count
                    if cycle_count >= 5:
                        cycle_confidence = "high"
                    elif cycle_count >= 3:
                        cycle_confidence = "medium"
                    else:
                        cycle_confidence = "low"

            # If we have HeatingCycleCoordinator data, use it directly
            if cycle_heating_rate is not None and cycle_heating_rate > 0.1:
                from datetime import timedelta
                temp_diff = self._target_temp - self._current_temp
                hours_needed = temp_diff / cycle_heating_rate
                minutes_needed = int(hours_needed * 60)

                # Add UFH buffer for underfloor heating systems
                minutes_needed += ufh_buffer

                minutes_needed = min(minutes_needed, 240)  # Cap at 4 hours

                recommended_start = next_block.start_time - timedelta(minutes=minutes_needed)

                self._attr_native_value = recommended_start.strftime("%H:%M")
                self._duration_minutes = minutes_needed
                self._heating_rate = cycle_heating_rate
                self._confidence = cycle_confidence
                self._summary = (
                    f"Start at {self._attr_native_value}"
                    f" ({minutes_needed} min to reach {self._target_temp:.1f}°C)"
                )
                if ufh_buffer > 0:
                    self._summary += f" (includes {ufh_buffer} min UFH buffer)"
                self._attr_available = True
                return

            # Fallback to SmartComfortManager
            advice = manager.get_preheat_advice(
                self._zone_id,
                self._target_temp,
                next_block.start_time,
                self._current_temp
            )

            if advice is None:
                # Not enough data to calculate heating rate
                self._attr_native_value = "Insufficient data"
                self._attr_available = True
                self._duration_minutes = None
                self._heating_rate = None
                self._confidence = "insufficient_data"
                temp_diff = self._target_temp - self._current_temp
                self._summary = f"Need +{temp_diff:.1f}°C by {self._target_time} (no heating history)"
                return

            # We have a valid preheat recommendation
            # Apply UFH buffer to SmartComfortManager advice
            from datetime import timedelta
            adjusted_duration = advice.estimated_duration_minutes + ufh_buffer
            adjusted_duration = min(adjusted_duration, 240)  # Cap at 4 hours
            adjusted_start = next_block.start_time - timedelta(minutes=adjusted_duration)

            self._attr_native_value = adjusted_start.strftime("%H:%M")
            self._duration_minutes = adjusted_duration
            self._heating_rate = advice.heating_rate
            self._confidence = advice.confidence
            self._summary = advice.to_summary()
            if ufh_buffer > 0:
                self._summary += f" (includes {ufh_buffer} min UFH buffer)"
            self._attr_available = True

        except Exception as e:
            _LOGGER.debug("Failed to update preheat advice for zone %s: %s", self._zone_id, e)
            self._attr_available = False


class TadoSmartComfortTargetSensor(TadoZoneSensor):
    _attr_has_entity_name = True

    """Smart Comfort Target Temperature sensor.

    Calculates the ideal target temperature using ASHRAE 55 Adaptive Comfort Model.
    This is the temperature at which the zone would be "Comfortable" according to
    the Comfort Level sensor.

    Formula: Comfort Temp = 0.31 × Outdoor_Temp + 17.8°C

    This provides a scientifically-validated, location-aware target that adapts
    to outdoor conditions. When outdoor temp is not available, falls back to
    seasonal thresholds based on latitude.

    State: Recommended target temperature (°C)
    """

    def __init__(self, coordinator, zone_id: str, zone_name: str, zone_type: str = "HEATING"):
        super().__init__(coordinator, zone_id, zone_name, zone_type)
        self._attr_name = "[CE] Comfort Target"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_zone_{zone_id}_comfort_target"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_icon = "mdi:thermometer-auto"
        self._attr_state_class = SensorStateClass.MEASUREMENT

        # Attributes
        self._current_temp: float | None = None
        self._outdoor_temp: float | None = None
        self._humidity: float | None = None
        self._comfort_model: str = "unknown"
        self._deviation: float | None = None

    @property
    def extra_state_attributes(self):
        return {
            "current_temperature": self._current_temp,
            "outdoor_temperature": self._outdoor_temp,
            "humidity": self._humidity,
            "comfort_model": _format_comfort_model(self._comfort_model),
            "deviation_from_comfort": self._deviation,
            "zone_type": _format_zone_type(self._zone_type),
        }

    @property
    def icon(self):
        """Dynamic icon based on deviation from comfort."""
        if self._deviation is None:
            return "mdi:thermometer-auto"
        if self._deviation < -2:
            return "mdi:thermometer-low"  # Too cold
        if self._deviation > 2:
            return "mdi:thermometer-high"  # Too hot
        return "mdi:thermometer-check"  # Comfortable

    @callback
    def update(self):
        """Update Smart Comfort target using ASHRAE 55 Adaptive Comfort Model."""
        try:
            if not self.hass:
                self._attr_available = False
                return

            # Get config_manager from coordinator (real-time config access)
            config_manager = self.coordinator.config_manager
            if not config_manager:
                self._attr_available = False
                return

            # Get zone data
            zone_data = self._get_zone_data()
            if not zone_data:
                self._attr_available = False
                return

            # Get current temperature
            sensor_data = zone_data.get('sensorDataPoints') or {}
            inside_temp = sensor_data.get('insideTemperature') or {}
            self._current_temp = inside_temp.get('celsius')

            # Get humidity
            humidity_data = sensor_data.get('humidity') or {}
            self._humidity = humidity_data.get('percentage')

            # Get outdoor temperature
            outdoor_entity = config_manager.get_outdoor_temp_entity()
            self._outdoor_temp = _get_outdoor_temp(self.hass, outdoor_entity, config_manager.get_use_feels_like())

            # Calculate comfort target using ASHRAE 55 or seasonal fallback
            comfort_target = self._calculate_comfort_target()

            if comfort_target is None:
                self._attr_available = False
                return

            # Round to 0.5°C (Tado's precision)
            comfort_target = round(comfort_target * 2) / 2

            # Calculate deviation from comfort
            if self._current_temp is not None:
                self._deviation = round(self._current_temp - comfort_target, 1)
            else:
                self._deviation = None

            self._attr_native_value = comfort_target
            self._attr_available = True

        except Exception as e:
            _LOGGER.debug("Failed to update Smart Comfort target for zone %s: %s", self._zone_id, e)
            self._attr_available = False

    def _calculate_comfort_target(self) -> float | None:
        """Calculate comfort target using ASHRAE 55 or seasonal fallback."""
        # Method 1: ASHRAE 55 Adaptive Comfort Model (if outdoor temp available)
        if self._outdoor_temp is not None:
            self._comfort_model = "adaptive"
            # Formula: Comfort Temp = 0.31 × Outdoor_Temp + 17.8°C
            return 0.31 * self._outdoor_temp + 17.8

        # Method 2: Seasonal fallback based on latitude
        self._comfort_model = "seasonal"
        return self._get_seasonal_comfort_target()

    def _get_seasonal_comfort_target(self) -> float:
        """Get comfort target based on season and latitude."""
        from datetime import datetime

        # Get latitude from HA config
        latitude = 51.5  # Default to London
        if self.hass and hasattr(self.hass.config, 'latitude'):
            latitude = self.hass.config.latitude or 51.5

        # Determine season (reverse for Southern Hemisphere)
        month = datetime.now().month
        is_southern = latitude < 0

        if is_southern:
            # Southern Hemisphere: reverse seasons
            if month in [12, 1, 2]:
                season = "summer"
            elif month in [6, 7, 8]:
                season = "winter"
            else:
                season = "transition"
        else:
            # Northern Hemisphere
            if month in [6, 7, 8]:
                season = "summer"
            elif month in [11, 12, 1, 2]:
                season = "winter"
            else:
                season = "transition"

        # Base comfort targets by season
        base_targets = {
            "summer": 24.0,
            "winter": 20.0,
            "transition": 22.0,
        }

        # Latitude adjustment
        abs_lat = abs(latitude)
        if abs_lat > 55:
            lat_offset = -1.0  # Nordic - prefer cooler
        elif abs_lat > 45:
            lat_offset = -0.5  # Northern Europe
        elif abs_lat < 30:
            lat_offset = 1.0   # Subtropical - prefer warmer
        elif abs_lat < 40:
            lat_offset = 0.5   # Mediterranean
        else:
            lat_offset = 0.0   # Temperate

        return base_targets[season] + lat_offset


