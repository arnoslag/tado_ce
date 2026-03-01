"""Display formatting helpers for Tado CE entities.

All internal-to-display value conversions live here.
Maps that also exist in const.py (overlay, window type) are
derived from const.py canonical dicts — not duplicated.
"""
from __future__ import annotations

from .const import OVERLAY_MODE_REVERSE_MAP, WINDOW_TYPE_REVERSE_MAP

# === Maps owned by this module (no equivalent in const.py) ===

WEATHER_STATE_MAP: dict[str, str] = {
    "CLOUDY_MOSTLY": "Mostly Cloudy", "CLOUDY_PARTLY": "Partly Cloudy",
    "CLOUDY": "Cloudy", "DRIZZLE": "Drizzle", "FOGGY": "Foggy",
    "NIGHT_CLEAR": "Clear Night", "NIGHT_CLOUDY": "Cloudy Night",
    "RAIN": "Rain", "SCATTERED_RAIN": "Scattered Rain", "SNOW": "Snow",
    "SUN": "Sunny", "THUNDERSTORMS": "Thunderstorms", "WINDY": "Windy",
}

ZONE_TYPE_DISPLAY_MAP: dict[str, str] = {
    "HEATING": "Heating", "AIR_CONDITIONING": "Air Conditioning", "HOT_WATER": "Hot Water",
}

COMFORT_MODEL_DISPLAY_MAP: dict[str, str] = {"adaptive": "Adaptive", "seasonal": "Seasonal"}

INSIGHT_TYPE_DISPLAY_MAP: dict[str, str] = {
    "mold_risk": "Mold Risk", "comfort": "Comfort", "battery": "Battery",
    "connection": "Connection", "window_predicted": "Open Window",
    "condensation": "Condensation", "preheat_timing": "Preheat Timing",
    "schedule_deviation": "Schedule Deviation", "heating_anomaly": "Heating Anomaly",
    "cross_zone_mold": "Cross-Zone Mold", "cross_zone_window": "Cross-Zone Open Window",
    "cross_zone_condensation": "Cross-Zone Condensation",
    "cross_zone_efficiency": "Cross-Zone Efficiency",
    "api_quota_planning": "API Quota", "weather_impact": "Weather Impact",
    "overlay_duration": "Overlay Duration", "schedule_gap": "Schedule Gap",
    "frequent_override": "Frequent Override", "away_heating": "Away Heating",
    "home_all_off": "Home All Off", "solar_gain": "Solar Gain",
    "solar_ac_load": "Solar AC Load", "frost_risk": "Frost Risk",
    "heating_season": "Heating Season", "heating_off_cold": "Heating Off Cold",
    "boiler_flow_anomaly": "Boiler Flow Anomaly",
    "early_start_disabled": "Early Start Disabled",
    "thermal_efficiency": "Thermal Efficiency",
    "temp_imbalance": "Temperature Imbalance",
    "humidity_imbalance": "Humidity Imbalance", "humidity_trend": "Humidity Trend",
    "device_limitation": "Device Limitation", "geofencing_offline": "Geofencing Offline",
    "api_usage_spike": "API Usage Spike",
}

API_STATUS_DISPLAY_MAP: dict[str, str] = {
    "ok": "OK", "warning": "Warning", "rate_limited": "Rate Limited",
}

CONFIDENCE_DISPLAY_MAP: dict[str, str] = {
    "no_schedule": "No Schedule", "insufficient_data": "Insufficient Data",
    "high": "High", "medium": "Medium", "low": "Low",
    "none": "None", "unknown": "Unknown",
}

TADO_MODE_DISPLAY_MAP: dict[str, str] = {"HOME": "Home", "AWAY": "Away"}
DATA_SOURCE_DISPLAY_MAP: dict[str, str] = {"home_state": "Home State", "zones": "Zones"}

BATTERY_STATE_DISPLAY_MAP: dict[str, str] = {
    "NORMAL": "Normal", "LOW": "Low", "CRITICAL": "Critical",
}
CONNECTION_STATE_DISPLAY_MAP: dict[bool, str] = {True: "Online", False: "Offline"}
CONNECTION_STATE_ATTR_MAP: dict[bool, str] = {True: "online", False: "offline"}


# === Generic lookup helper ===

def _lookup(mapping: dict, value, fallback_fn=None) -> str:
    """Look up value in mapping. Falsy value -> 'Unknown', unmapped -> fallback."""
    if not value and value is not False:
        return "Unknown"
    if value in mapping:
        return mapping[value]
    if fallback_fn:
        return fallback_fn(value)
    return str(value).replace("_", " ").title()


# === Format functions ===

def format_zone_type(zone_type: str) -> str:
    """Convert internal zone_type to user-friendly display value."""
    return ZONE_TYPE_DISPLAY_MAP.get(zone_type, zone_type)

def format_window_type(window_type: str) -> str:
    """Convert internal window_type to user-friendly display value."""
    return WINDOW_TYPE_REVERSE_MAP.get(window_type, window_type)

def format_comfort_model(comfort_model: str) -> str:
    """Convert internal comfort_model to user-friendly display value."""
    return _lookup(COMFORT_MODEL_DISPLAY_MAP, comfort_model, lambda v: v.title())

def format_insight_type(insight_type: str) -> str:
    """Convert internal insight_type to user-friendly display value."""
    return _lookup(INSIGHT_TYPE_DISPLAY_MAP, insight_type)

def format_priority(priority: str) -> str:
    """Convert internal priority to Title Case display value."""
    return priority.title() if priority else "None"

def format_api_status(status: str) -> str:
    """Convert internal API status to user-friendly display value."""
    return _lookup(API_STATUS_DISPLAY_MAP, status)

def format_overlay_type(overlay_type) -> str:
    """Convert internal overlay_type to user-friendly display value."""
    if overlay_type is None:
        return "None"
    return OVERLAY_MODE_REVERSE_MAP.get(
        overlay_type, str(overlay_type).replace("_", " ").title()
    )

def format_confidence(confidence: str) -> str:
    """Convert internal confidence to user-friendly display value."""
    return _lookup(CONFIDENCE_DISPLAY_MAP, confidence)

def format_tado_mode(mode: str) -> str:
    """Convert internal tado mode to user-friendly display value."""
    return _lookup(TADO_MODE_DISPLAY_MAP, mode, lambda v: v.title())

def format_data_source(source: str) -> str:
    """Convert internal data source to user-friendly display value."""
    return _lookup(DATA_SOURCE_DISPLAY_MAP, source)

def format_weather_state(state: str) -> str:
    """Convert internal weather state to user-friendly display value."""
    return _lookup(WEATHER_STATE_MAP, state)

def format_battery_state(state: str) -> str:
    """Convert API batteryState to user-friendly display value."""
    return _lookup(BATTERY_STATE_DISPLAY_MAP, state, lambda v: v.title())

def format_connection_state(connected) -> str:
    """Convert connectionState.value (bool) to display value. True -> 'Online', False/None -> 'Offline'."""
    return CONNECTION_STATE_DISPLAY_MAP.get(bool(connected) if connected is not None else False, "Offline")

def format_connection_state_attr(connected) -> str:
    """Convert connectionState.value (bool) to lowercase for extra_state_attributes."""
    return CONNECTION_STATE_ATTR_MAP.get(bool(connected) if connected is not None else False, "offline")

def format_power_state(power: str) -> str:
    """Convert zone power setting to display value. Falsy -> 'Unknown'."""
    return power if power else "Unknown"
