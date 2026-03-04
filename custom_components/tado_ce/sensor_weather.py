"""Tado CE Weather Sensors — outside temperature, solar, weather state."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .format_helpers import WEATHER_STATE_MAP

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class TadoOutsideTemperatureSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Outside temperature from Tado weather data."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "Outside Temp"
        self.entity_id = "sensor.tado_ce_outside_temperature"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_outside_temp"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_available = False
        self._attr_native_value = None
        self._timestamp = None

    @property
    def extra_state_attributes(self):
        return {"timestamp": self._timestamp}

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self):
        try:
            data = (self.coordinator.data or {}).get("weather")
            if data:
                temp_data = data.get('outsideTemperature') or {}
                self._attr_native_value = temp_data.get('celsius')
                self._timestamp = temp_data.get('timestamp')
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoSolarIntensitySensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Solar intensity from Tado weather data."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "Solar Intensity"
        self.entity_id = "sensor.tado_ce_solar_intensity"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_solar_intensity"
        self._attr_icon = "mdi:white-balance-sunny"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_available = False
        self._attr_native_value = None
        self._timestamp = None

    @property
    def extra_state_attributes(self):
        return {"timestamp": self._timestamp}

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self):
        try:
            data = (self.coordinator.data or {}).get("weather")
            if data:
                solar_data = data.get('solarIntensity') or {}
                self._attr_native_value = solar_data.get('percentage')
                self._timestamp = solar_data.get('timestamp')
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False


class TadoWeatherStateSensor(CoordinatorEntity["TadoDataUpdateCoordinator"], SensorEntity):
    _attr_has_entity_name = True

    """Weather state from Tado weather data."""

    def __init__(self, coordinator: "TadoDataUpdateCoordinator"):
        super().__init__(coordinator)
        self._attr_name = "Weather"
        self.entity_id = "sensor.tado_ce_weather_state"
        self._attr_unique_id = f"tado_ce_{coordinator.home_id}_weather_state"
        self._attr_icon = "mdi:weather-partly-cloudy"
        self._attr_available = False
        self._attr_native_value = None
        self._raw_state = None
        self._timestamp = None

    @property
    def icon(self):
        icons = {
            "SUN": "mdi:weather-sunny",
            "CLOUDY": "mdi:weather-cloudy",
            "CLOUDY_MOSTLY": "mdi:weather-cloudy",
            "CLOUDY_PARTLY": "mdi:weather-partly-cloudy",
            "RAIN": "mdi:weather-rainy",
            "SCATTERED_RAIN": "mdi:weather-partly-rainy",
            "DRIZZLE": "mdi:weather-rainy",
            "SNOW": "mdi:weather-snowy",
            "FOGGY": "mdi:weather-fog",
            "NIGHT_CLEAR": "mdi:weather-night",
            "NIGHT_CLOUDY": "mdi:weather-night-partly-cloudy",
            "THUNDERSTORMS": "mdi:weather-lightning",
            "WINDY": "mdi:weather-windy",
        }
        return icons.get(self._raw_state, "mdi:weather-partly-cloudy")

    @property
    def extra_state_attributes(self):
        return {
            "raw_state": self._raw_state,
            "timestamp": self._timestamp,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        self.update()
        self.async_write_ha_state()

    @callback
    def update(self):
        try:
            data = (self.coordinator.data or {}).get("weather")
            if data:
                weather_data = data.get('weatherState') or {}
                self._raw_state = weather_data.get('value')
                self._timestamp = weather_data.get('timestamp')
                self._attr_native_value = WEATHER_STATE_MAP.get(self._raw_state, self._raw_state)
                self._attr_available = self._attr_native_value is not None
            else:
                self._attr_available = False
        except Exception:
            self._attr_available = False
