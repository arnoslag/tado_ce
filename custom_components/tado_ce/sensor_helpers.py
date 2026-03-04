"""Shared helper functions for Tado CE sensor entities.

- get_outdoor_temperature(): outdoor temperature lookup from configured entity
"""
from __future__ import annotations

import logging
from typing import Optional

_LOGGER = logging.getLogger(__name__)


def get_outdoor_temperature(hass, entity_id: str, use_feels_like: bool = False) -> Optional[float]:
    """Get outdoor temperature from a configured entity.

    Supports both weather entities (reads 'temperature' attribute) and
    regular sensor entities (reads state value).

    When *use_feels_like* is True and the source is a weather entity,
    tries 'apparent_temperature' then 'feels_like' before falling back
    to 'temperature'.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID of outdoor temperature sensor or weather entity
        use_feels_like: Whether to prefer feels-like temperature

    Returns:
        Outdoor temperature in °C, or None if not available
    """
    if not hass or not entity_id:
        return None

    try:
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None

        if entity_id.startswith("weather."):
            if use_feels_like:
                temp = state.attributes.get("apparent_temperature")
                if temp is None:
                    temp = state.attributes.get("feels_like")
                if temp is None:
                    temp = state.attributes.get("temperature")
            else:
                temp = state.attributes.get("temperature")

            if temp is not None:
                return float(temp)
        else:
            return float(state.state)
    except (ValueError, TypeError):
        pass
    except Exception as e:
        _LOGGER.debug("Error getting outdoor temperature from %s: %s", entity_id, e)

    return None


def get_effective_temperature(
    hass,
    zone_id: str,
    room_temp: float,
    config_manager=None,
    zone_config_manager=None,
) -> tuple:
    """Get effective temperature for mold risk calculation.

    2-tier strategy:
    - Tier 1: Surface temperature estimation (if outdoor temp + window type available)
    - Tier 2: Room average temperature (fallback)

    Accepts config_manager/zone_config_manager directly
    instead of entry_id (CoordinatorEntity migration).
    """
    from .const import DEFAULT_WINDOW_TYPE, WINDOW_U_VALUES

    fallback = (room_temp, None, None, "Room Average", 0.0)

    try:
        if not config_manager:
            return fallback

        outdoor_entity = config_manager.get_outdoor_temp_entity()
        if not outdoor_entity:
            return fallback

        outdoor_temp = get_outdoor_temperature(
            hass, outdoor_entity, config_manager.get_use_feels_like()
        )
        if outdoor_temp is None:
            return fallback

        # Get U-value and surface offset (per-zone or global)
        if zone_config_manager:
            u_value = zone_config_manager.get_window_u_value(zone_id)
            surface_offset = zone_config_manager.get_surface_temp_offset(zone_id)
        else:
            window_type = config_manager.get_mold_risk_window_type()
            u_value = WINDOW_U_VALUES.get(window_type, WINDOW_U_VALUES[DEFAULT_WINDOW_TYPE])
            surface_offset = 0.0

        # Calculate surface temperature using heat transfer physics
        # Inline the formula to avoid circular import of _calculate_surface_temperature
        # T_surface = T_indoor - U * (T_indoor - T_outdoor) / h_internal
        # h_internal ≈ 7.7 W/(m²·K) for still air (BS EN ISO 6946)
        h_internal = 7.7
        surface_temp = round(room_temp - u_value * (room_temp - outdoor_temp) / h_internal, 1)

        # Apply calibration offset
        if surface_offset != 0.0:
            surface_temp = round(surface_temp + surface_offset, 1)
            source = "Calibrated"
        else:
            source = "Estimated"

        return (surface_temp, outdoor_temp, surface_temp, source, surface_offset)

    except Exception as e:
        _LOGGER.debug("Error determining temperature source for zone %s: %s", zone_id, e)
        return fallback


def calculate_surface_rh(effective_temp: float, dew_point: float) -> Optional[int]:
    """Calculate relative humidity at the window surface.

    Uses the Magnus-Tetens formula for saturation vapour pressure.
    Mold typically grows when surface RH exceeds ~70-80 %.

    Args:
        effective_temp: Surface (or room) temperature in °C
        dew_point: Dew point temperature in °C

    Returns:
        Surface relative humidity as integer percentage (0-100), or None on error
    """
    import math

    try:
        def _svp(temp: float) -> float:
            return 6.112 * math.exp((17.67 * temp) / (temp + 243.5))

        surface_rh = (_svp(dew_point) / _svp(effective_temp)) * 100
        return round(min(100, max(0, surface_rh)))
    except Exception:
        return None
