"""Tado CE centralized physics calculations — dew point, surface temp, risk classifiers, comfort models.

Single source of truth for all thermodynamic formulas, risk classification,
and comfort calculations. All functions return exact (unrounded) values;
rounding is applied only at the display layer in sensor classes.

References:
    - Magnus-Tetens: Alduchov & Eskridge 1996 (WMO recommended)
    - Surface temp: ISO 6946 / ASHRAE 160
    - Comfort: ASHRAE 55 Adaptive Comfort Model
"""

from __future__ import annotations

import logging
import math

from .const import INTERIOR_SURFACE_HEAT_TRANSFER_COEFFICIENT

_LOGGER = logging.getLogger(__name__)

# ============ Magnus-Tetens Constants (Alduchov & Eskridge 1996) ============
# Valid range: -40°C to 50°C, accuracy ±0.1%
MAGNUS_A: float = 17.27
MAGNUS_B: float = 237.7  # °C

# ============ Mold Risk Thresholds (margin = effective_temp - dew_point) ============
MOLD_RISK_CRITICAL: float = 3.0  # °C — margin < 3 → Critical
MOLD_RISK_HIGH: float = 5.0  # °C — margin < 5 → High
MOLD_RISK_MEDIUM: float = 7.0  # °C — margin < 7 → Medium

# ============ Condensation Risk Thresholds — HEATING ============
# margin = surface_temp - indoor_dew_point, uses <= comparisons
CONDENSATION_HEATING_CRITICAL: float = 1.0  # °C
CONDENSATION_HEATING_HIGH: float = 3.0  # °C
CONDENSATION_HEATING_MEDIUM: float = 5.0  # °C
CONDENSATION_HEATING_LOW: float = 7.0  # °C

# ============ Condensation Risk Thresholds — AC ============
# margin = window_outer_surface_temp - outdoor_dew_point, uses < comparisons
CONDENSATION_AC_CRITICAL: float = 2.0  # °C
CONDENSATION_AC_HIGH: float = 4.0  # °C
CONDENSATION_AC_MEDIUM: float = 6.0  # °C

# ============ ASHRAE 55 Adaptive Comfort Model ============
ASHRAE_SLOPE: float = 0.31
ASHRAE_INTERCEPT: float = 17.8  # °C

# ============ Seasonal Comfort Constants ============
# Latitude offset by climate zone (Decision D-3: conservative scale)
SEASONAL_LAT_OFFSETS: tuple[tuple[float, float], ...] = (
    (55.0, -1.0),  # Nordic/Subarctic
    (45.0, -0.5),  # Northern Europe/Canada
    (40.0, 0.0),  # Temperate (default)
    (30.0, 0.5),  # Mediterranean
    (0.0, 1.0),  # Subtropical
)

SEASONAL_BASE_TARGETS: dict[str, float] = {
    "summer": 24.0,
    "winter": 20.0,
    "transition": 22.0,
}

# ============ Comfort Level Thresholds ============
COMFORT_COLD: float = 16.0  # °C — below → Cold
COMFORT_COOL: float = 18.0  # °C — below → Cool
COMFORT_WARM: float = 24.0  # °C — above → Warm
COMFORT_HOT: float = 26.0  # °C — above → Hot

# ============ Cooling Rate Thresholds (°C/min) ============
COOLING_RATE_MIN: float = -5.0  # °C/min — floor clamp for outlier rejection
COOLING_RATE_STABLE: float = -0.1  # °C/min — abs(rate) below this → room is stable


# ============ Dew Point Calculation ============


def calculate_dew_point(temperature: float, humidity: float) -> float:
    """Calculate dew point using Magnus-Tetens formula (Alduchov & Eskridge 1996).

    Formula: Td = (b × α) / (a - α)
    where α = (a × T) / (b + T) + ln(RH/100)

    Args:
        temperature: Air temperature in °C.
        humidity: Relative humidity in %.

    Returns:
        Dew point temperature in °C (exact, no rounding).
    """
    humidity = max(1.0, min(100.0, humidity))
    alpha = (MAGNUS_A * temperature) / (MAGNUS_B + temperature) + math.log(humidity / 100.0)
    return (MAGNUS_B * alpha) / (MAGNUS_A - alpha)


# ============ Surface Temperature Calculation ============


def calculate_surface_temperature(
    indoor_temp: float,
    outdoor_temp: float,
    u_value: float,
    h: float = INTERIOR_SURFACE_HEAT_TRANSFER_COEFFICIENT,
) -> float:
    """Calculate window surface temperature using heat transfer physics.

    Formula: T_surface = T_indoor - (T_indoor - T_outdoor) × U / (U + h)

    Args:
        indoor_temp: Indoor temperature in °C.
        outdoor_temp: Outdoor temperature in °C.
        u_value: Window U-value (thermal transmittance) in W/m²K.
        h: Interior surface heat transfer coefficient in W/m²K.
           Default 8.0 (ISO 6946 combined convective+radiative).

    Returns:
        Estimated surface temperature in °C (exact, no rounding).
    """
    temp_diff = indoor_temp - outdoor_temp
    return indoor_temp - (temp_diff * u_value / (u_value + h))


# ============ Surface Relative Humidity ============


def calculate_surface_rh(effective_temp: float, dew_point: float) -> int | None:
    """Calculate relative humidity at the window surface.

    Uses Magnus-Tetens saturation vapour pressure with unified constants
    (a=17.27, b=237.7) matching calculate_dew_point.

    Args:
        effective_temp: Surface (or room) temperature in °C.
        dew_point: Dew point temperature in °C.

    Returns:
        Surface relative humidity as integer percentage (0-100), or None on error.
    """
    try:

        def _svp(temp: float) -> float:
            """Calculate saturation vapour pressure."""
            return 6.112 * math.exp((MAGNUS_A * temp) / (temp + MAGNUS_B))

        surface_rh = (_svp(dew_point) / _svp(effective_temp)) * 100.0
        return round(min(100.0, max(0.0, surface_rh)))
    except Exception:
        _LOGGER.debug(
            "Failed to calculate surface RH (effective_temp=%s, dew_point=%s)",
            effective_temp,
            dew_point,
        )
        return None


# ============ Mold Risk Classification ============


def classify_mold_risk_by_margin(margin: float) -> str:
    """Classify mold risk level from pre-computed margin.

    Args:
        margin: Temperature margin (effective_temp - dew_point) in °C.

    Returns:
        Risk level: "Critical", "High", "Medium", or "Low".
    """
    if margin < MOLD_RISK_CRITICAL:
        return "Critical"
    if margin < MOLD_RISK_HIGH:
        return "High"
    if margin < MOLD_RISK_MEDIUM:
        return "Medium"
    return "Low"


def classify_mold_risk_level(inside_temp: float, humidity: float) -> str:
    """Classify mold risk level from temperature and humidity.

    Uses exact (unrounded) dew point to preserve monotonicity:
    higher temperature must never worsen the risk level.

    Args:
        inside_temp: Indoor temperature in °C.
        humidity: Relative humidity in %.

    Returns:
        Risk level: "Critical", "High", "Medium", or "Low".
    """
    dew_point = calculate_dew_point(inside_temp, humidity)
    margin = inside_temp - dew_point
    return classify_mold_risk_by_margin(margin)


# ============ Condensation Risk Classification ============


def classify_condensation_risk(margin: float, zone_type: str) -> str:
    """Classify condensation risk from margin and zone type.

    HEATING zones use <= thresholds (accounts for cold spots at window edges).
    AC zones use < thresholds.

    Args:
        margin: Temperature margin (surface_temp - dew_point) in °C.
        zone_type: "HEATING" or "AIR_CONDITIONING".

    Returns:
        HEATING: "Critical", "High", "Medium", "Low", or "None".
        AC: "Critical", "High", "Medium", or "Low".
    """
    if zone_type == "HEATING":
        if margin <= CONDENSATION_HEATING_CRITICAL:
            return "Critical"
        if margin <= CONDENSATION_HEATING_HIGH:
            return "High"
        if margin <= CONDENSATION_HEATING_MEDIUM:
            return "Medium"
        if margin <= CONDENSATION_HEATING_LOW:
            return "Low"
        return "None"

    # AC zone
    if margin < CONDENSATION_AC_CRITICAL:
        return "Critical"
    if margin < CONDENSATION_AC_HIGH:
        return "High"
    if margin < CONDENSATION_AC_MEDIUM:
        return "Medium"
    return "Low"


# ============ Comfort Level Classification ============


def classify_comfort_level(inside_temp: float) -> str:
    """Classify comfort level from indoor temperature.

    Args:
        inside_temp: Indoor temperature in °C.

    Returns:
        Comfort level: "Cold", "Cool", "Comfortable", "Warm", or "Hot".
    """
    if inside_temp < COMFORT_COLD:
        return "Cold"
    if inside_temp < COMFORT_COOL:
        return "Cool"
    if inside_temp <= COMFORT_WARM:
        return "Comfortable"
    if inside_temp <= COMFORT_HOT:
        return "Warm"
    return "Hot"


# ============ ASHRAE 55 Adaptive Comfort ============


def calculate_ashrae_comfort_temp(outdoor_temp: float) -> float:
    """Calculate neutral comfort temperature using ASHRAE 55 Adaptive Comfort Model.

    Formula: Comfort_temp = 0.31 × outdoor_temp + 17.8°C

    Args:
        outdoor_temp: Outdoor temperature in °C.

    Returns:
        Neutral comfort temperature in °C (exact, no rounding).
    """
    return ASHRAE_SLOPE * outdoor_temp + ASHRAE_INTERCEPT


# ============ Seasonal Comfort Target ============


def calculate_seasonal_comfort_target(latitude: float, month: int) -> float:
    """Calculate comfort target based on season and latitude.

    Pure function — no HA dependencies. Caller provides latitude and month.

    Args:
        latitude: Geographic latitude in degrees (negative = Southern Hemisphere).
        month: Calendar month (1-12).

    Returns:
        Comfort target temperature in °C.
    """
    is_southern = latitude < 0

    # Determine season (reverse for Southern Hemisphere)
    effective_month = month
    if is_southern:
        if month in (12, 1, 2):
            season = "summer"
        elif month in (6, 7, 8):
            season = "winter"
        else:
            season = "transition"
    elif effective_month in (6, 7, 8):
        season = "summer"
    elif effective_month in (11, 12, 1, 2):
        season = "winter"
    else:
        season = "transition"

    # Latitude offset
    abs_lat = abs(latitude)
    lat_offset = 0.0
    for threshold, offset in SEASONAL_LAT_OFFSETS:
        if abs_lat > threshold:
            lat_offset = offset
            break

    return SEASONAL_BASE_TARGETS[season] + lat_offset

# ============ Cooling Rate Crossover Estimation ============


def estimate_cooling_crossover(
    current_temp: float,
    target_temp: float,
    cooling_rate: float,
) -> float | None:
    """Estimate hours until temperature crosses below target due to cooling.

    Uses linear extrapolation from current cooling rate.
    Pure function — no HA dependencies.

    Args:
        current_temp: Current room temperature in °C.
        target_temp: Target temperature in °C.
        cooling_rate: Cooling rate in °C/h (negative value).

    Returns:
        Hours until crossover (positive float), or None if:
        - current_temp < target_temp (already below target)
        - cooling_rate >= COOLING_RATE_STABLE (stable or warming)
    """
    if current_temp < target_temp:
        return None

    if cooling_rate >= COOLING_RATE_STABLE:
        return None

    # Clamp extreme rates
    effective_rate = max(cooling_rate, COOLING_RATE_MIN)

    temp_margin = current_temp - target_temp
    hours = temp_margin / abs(effective_rate)

    return hours

