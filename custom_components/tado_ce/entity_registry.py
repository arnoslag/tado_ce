"""Tado CE Central Entity Registry — single source of truth for entity metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.const import EntityCategory


@dataclass(frozen=True, slots=True)
class EntityMeta:
    """Represent metadata for a single entity type."""

    translation_key: str | None
    unique_id_suffix: str
    entity_category: str | None  # "diagnostic", "config", or None
    icon: str | None = None
    enabled_default: bool = True
    legacy_name: str | None = None


# ---------------------------------------------------------------------------
# Registry — keyed by "{platform}_{translation_key}"
# unique_id_suffix does NOT include the "tado_ce_{home_id}_" prefix.
# Entity classes construct the full unique_id at runtime.
# ---------------------------------------------------------------------------

ENTITY_REGISTRY: dict[str, EntityMeta] = {
    # ===================================================================
    # Hub Sensors (sensor_hub.py) — 12 entries, all DIAGNOSTIC
    # ===================================================================
    "sensor_home_id": EntityMeta(
        translation_key="home_id",
        unique_id_suffix="home_id",
        entity_category="diagnostic",
        icon="mdi:home",
        enabled_default=False,
        legacy_name="Home ID",
    ),
    "sensor_api_usage": EntityMeta(
        translation_key="api_usage",
        unique_id_suffix="api_usage",
        entity_category="diagnostic",
        icon=None,  # dynamic icon based on status
        legacy_name="API Usage",
    ),
    "sensor_api_reset": EntityMeta(
        translation_key="api_reset",
        unique_id_suffix="api_reset",
        entity_category="diagnostic",
        icon="mdi:timer-refresh",
        legacy_name="API Reset",
    ),
    "sensor_api_limit": EntityMeta(
        translation_key="api_limit",
        unique_id_suffix="api_limit",
        entity_category="diagnostic",
        icon="mdi:speedometer",
        legacy_name="API Limit",
    ),
    "sensor_api_status": EntityMeta(
        translation_key="api_status",
        unique_id_suffix="api_status",
        entity_category="diagnostic",
        icon=None,  # dynamic icon based on status
        legacy_name="API Status",
    ),
    "sensor_token_status": EntityMeta(
        translation_key="token_status",
        unique_id_suffix="token_status",
        entity_category="diagnostic",
        icon=None,  # dynamic icon based on status
        enabled_default=False,
        legacy_name="Token Status",
    ),
    "sensor_zone_count": EntityMeta(
        translation_key="zone_count",
        unique_id_suffix="zone_count",
        entity_category="diagnostic",
        icon="mdi:home-thermometer",
        legacy_name="Zone Count",
    ),
    "sensor_last_sync": EntityMeta(
        translation_key="last_sync",
        unique_id_suffix="last_sync",
        entity_category="diagnostic",
        icon="mdi:sync",
        legacy_name="Last Sync",
    ),
    "sensor_next_sync": EntityMeta(
        translation_key="next_sync",
        unique_id_suffix="next_sync",
        entity_category="diagnostic",
        icon="mdi:clock-outline",
        legacy_name="Next Sync",
    ),
    "sensor_polling_interval": EntityMeta(
        translation_key="polling_interval",
        unique_id_suffix="polling_interval",
        entity_category="diagnostic",
        icon="mdi:timer-outline",
        enabled_default=False,
        legacy_name="Polling Interval",
    ),
    "sensor_call_history": EntityMeta(
        translation_key="call_history",
        unique_id_suffix="call_history",
        entity_category="diagnostic",
        icon="mdi:history",
        enabled_default=False,
        legacy_name="Call History",
    ),
    "sensor_api_breakdown": EntityMeta(
        translation_key="api_breakdown",
        unique_id_suffix="api_breakdown",
        entity_category="diagnostic",
        icon="mdi:chart-bar",
        enabled_default=False,
        legacy_name="API Breakdown",
    ),
    # ===================================================================
    # Weather Sensors (sensor_weather.py) — 3 entries, all DIAGNOSTIC
    # ===================================================================
    "sensor_outside_temp": EntityMeta(
        translation_key="outside_temp",
        unique_id_suffix="outside_temp",
        entity_category="diagnostic",
        icon=None,  # uses device_class temperature
        legacy_name="Outside Temp",
    ),
    "sensor_solar_intensity": EntityMeta(
        translation_key="solar_intensity",
        unique_id_suffix="solar_intensity",
        entity_category="diagnostic",
        icon="mdi:white-balance-sunny",
        legacy_name="Solar Intensity",
    ),
    "sensor_weather": EntityMeta(
        translation_key="weather",
        unique_id_suffix="weather_state",
        entity_category="diagnostic",
        icon="mdi:weather-partly-cloudy",  # default; dynamic icon in entity
        legacy_name="Weather",
    ),
    # ===================================================================
    # Zone Core Sensors (sensor_zone.py) — 7 entries + 1 hot water power
    # ===================================================================
    "sensor_temperature": EntityMeta(
        translation_key="temperature",
        unique_id_suffix="zone_{zone_id}_temp",
        entity_category=None,
        icon=None,  # uses device_class temperature
        legacy_name="Temp",
    ),
    "sensor_humidity": EntityMeta(
        translation_key="humidity",
        unique_id_suffix="zone_{zone_id}_humidity",
        entity_category=None,
        icon=None,  # uses device_class humidity
        legacy_name="Humidity",
    ),
    "sensor_heating_power": EntityMeta(
        translation_key="heating_power",
        unique_id_suffix="zone_{zone_id}_heating",
        entity_category="diagnostic",
        icon="mdi:radiator",
        legacy_name="Heating",
    ),
    "sensor_ac_power": EntityMeta(
        translation_key="ac_power",
        unique_id_suffix="zone_{zone_id}_ac",
        entity_category="diagnostic",
        icon="mdi:air-conditioner",
        legacy_name="AC",
    ),
    "sensor_boiler_flow_temp": EntityMeta(
        translation_key="boiler_flow_temp",
        unique_id_suffix="boiler_flow_temp",  # hub-level, no zone_id
        entity_category="diagnostic",
        icon="mdi:water-boiler",
        legacy_name="Boiler Flow Temp",
    ),
    "sensor_target": EntityMeta(
        translation_key="target",
        unique_id_suffix="zone_{zone_id}_target",
        entity_category=None,
        icon="mdi:thermometer-check",
        legacy_name="Target",
    ),
    "sensor_overlay": EntityMeta(
        translation_key="overlay",
        unique_id_suffix="zone_{zone_id}_overlay",
        entity_category="diagnostic",
        icon="mdi:calendar-clock",
        legacy_name="Overlay",
    ),
    "sensor_power": EntityMeta(
        translation_key="power",
        unique_id_suffix="zone_{zone_id}_power",
        entity_category="diagnostic",
        icon="mdi:power",
        legacy_name="Power",
    ),
    # ===================================================================
    # Smart Comfort Sensors (sensor_smart_comfort.py) — 5 entries
    # ===================================================================
    "sensor_schedule_deviation": EntityMeta(
        translation_key="schedule_deviation",
        unique_id_suffix="zone_{zone_id}_schedule_deviation",
        entity_category="diagnostic",
        icon="mdi:chart-timeline-variant",  # default; dynamic icon in entity
        legacy_name="Schedule Deviation",
    ),
    "sensor_next_schedule": EntityMeta(
        translation_key="next_schedule",
        unique_id_suffix="zone_{zone_id}_next_schedule",
        entity_category="diagnostic",
        icon="mdi:calendar-clock",
        legacy_name="Next Schedule",
    ),
    "sensor_next_sched_temp": EntityMeta(
        translation_key="next_sched_temp",
        unique_id_suffix="zone_{zone_id}_next_sched_temp",
        entity_category="diagnostic",
        icon="mdi:thermometer-chevron-up",  # default; dynamic icon in entity
        legacy_name="Next Sched Temp",
    ),
    "sensor_preheat_advisor": EntityMeta(
        translation_key="preheat_advisor",
        unique_id_suffix="zone_{zone_id}_preheat_advisor",
        entity_category="diagnostic",
        icon="mdi:clock-start",  # default; dynamic icon in entity
        legacy_name="Preheat Advisor",
    ),
    "sensor_comfort_target": EntityMeta(
        translation_key="comfort_target",
        unique_id_suffix="zone_{zone_id}_comfort_target",
        entity_category="diagnostic",
        icon="mdi:thermometer-auto",  # default; dynamic icon in entity
        legacy_name="Comfort Target",
    ),
    # ===================================================================
    # Environment Sensors (sensor_environment.py) — 6 entries, all DIAGNOSTIC
    # ===================================================================
    "sensor_mold_risk": EntityMeta(
        translation_key="mold_risk",
        unique_id_suffix="zone_{zone_id}_mold_risk",
        entity_category="diagnostic",
        icon="mdi:mushroom",
        legacy_name="Mold Risk",
    ),
    "sensor_mold_risk_pct": EntityMeta(
        translation_key="mold_risk_pct",
        unique_id_suffix="zone_{zone_id}_mold_risk_pct",
        entity_category="diagnostic",
        icon="mdi:water-percent",
        legacy_name="Mold Risk %",
    ),
    "sensor_condensation_risk": EntityMeta(
        translation_key="condensation_risk",
        unique_id_suffix="zone_{zone_id}_condensation",
        entity_category="diagnostic",
        icon="mdi:water-alert",
        legacy_name="Condensation",
    ),
    "sensor_surface_temp": EntityMeta(
        translation_key="surface_temp",
        unique_id_suffix="zone_{zone_id}_surface_temp",
        entity_category="diagnostic",
        icon="mdi:thermometer-lines",
        legacy_name="Surface Temp",
    ),
    "sensor_dew_point": EntityMeta(
        translation_key="dew_point",
        unique_id_suffix="zone_{zone_id}_dew_point",
        entity_category="diagnostic",
        icon="mdi:water-thermometer",
        legacy_name="Dew Point",
    ),
    "sensor_comfort_level": EntityMeta(
        translation_key="comfort_level",
        unique_id_suffix="zone_{zone_id}_comfort_level",
        entity_category="diagnostic",
        icon="mdi:air-filter",
        legacy_name="Comfort Level",
    ),
    # ===================================================================
    # Thermal Sensors (sensor_thermal.py) — 6 entries, all DIAGNOSTIC, all disabled by default
    # ===================================================================
    "sensor_thermal_inertia": EntityMeta(
        translation_key="thermal_inertia",
        unique_id_suffix="zone_{zone_id}_thermal_inertia",
        entity_category="diagnostic",
        icon="mdi:timer-sand",
        enabled_default=False,
        legacy_name="Thermal Inertia",
    ),
    "sensor_heating_rate": EntityMeta(
        translation_key="heating_rate",
        unique_id_suffix="zone_{zone_id}_heating_rate",
        entity_category="diagnostic",
        icon="mdi:trending-up",
        enabled_default=False,
        legacy_name="Heating Rate",
    ),
    "sensor_preheat_time": EntityMeta(
        translation_key="preheat_time",
        unique_id_suffix="zone_{zone_id}_preheat_time",
        entity_category="diagnostic",
        icon="mdi:clock-fast",
        enabled_default=False,
        legacy_name="Preheat Time",
    ),
    "sensor_confidence": EntityMeta(
        translation_key="confidence",
        unique_id_suffix="zone_{zone_id}_confidence",
        entity_category="diagnostic",
        icon="mdi:chart-line",
        enabled_default=False,
        legacy_name="Confidence",
    ),
    "sensor_heat_accel": EntityMeta(
        translation_key="heat_accel",
        unique_id_suffix="zone_{zone_id}_heat_accel",
        entity_category="diagnostic",
        icon="mdi:chart-bell-curve-cumulative",
        enabled_default=False,
        legacy_name="Heat Accel",
    ),
    "sensor_approach_factor": EntityMeta(
        translation_key="approach_factor",
        unique_id_suffix="zone_{zone_id}_approach_factor",
        entity_category="diagnostic",
        icon="mdi:target",
        enabled_default=False,
        legacy_name="Approach Factor",
    ),
    # ===================================================================
    # Insight Sensors (sensor_insight.py) — 2 entries, all DIAGNOSTIC
    # ===================================================================
    "sensor_home_insights": EntityMeta(
        translation_key="home_insights",
        unique_id_suffix="home_insights",  # hub-level, no zone_id
        entity_category="diagnostic",
        icon=None,  # dynamic icon based on priority
        legacy_name="Home Insights",
    ),
    "sensor_insights": EntityMeta(
        translation_key="insights",
        unique_id_suffix="zone_{zone_id}_insights",
        entity_category="diagnostic",
        icon=None,  # dynamic icon based on priority
        legacy_name="Insights",
    ),
    # ===================================================================
    # Device Sensors (sensor_device.py) — 4 entries (2 base + 2 suffixed), all DIAGNOSTIC
    # ===================================================================
    "sensor_battery": EntityMeta(
        translation_key="battery",
        unique_id_suffix="device_{serial}_battery",
        entity_category="diagnostic",
        icon="mdi:battery",
        legacy_name="Battery",
    ),
    "sensor_battery_suffixed": EntityMeta(
        translation_key="battery_suffixed",
        unique_id_suffix="device_{serial}_battery",
        entity_category="diagnostic",
        icon="mdi:battery",
        legacy_name="Battery{device_suffix}",
    ),
    "sensor_connection": EntityMeta(
        translation_key="connection",
        unique_id_suffix="device_{serial}_connection",
        entity_category="diagnostic",
        icon="mdi:wifi",
        legacy_name="Connection",
    ),
    "sensor_connection_suffixed": EntityMeta(
        translation_key="connection_suffixed",
        unique_id_suffix="device_{serial}_connection",
        entity_category="diagnostic",
        icon="mdi:wifi",
        legacy_name="Connection{device_suffix}",
    ),
    # ===================================================================
    # Binary Sensors (binary_sensor.py) — 5 entries
    # ===================================================================
    "binary_sensor_home": EntityMeta(
        translation_key="home",
        unique_id_suffix="home",  # hub-level
        entity_category="diagnostic",
        icon=None,  # uses device_class
        legacy_name="Home",
    ),
    "binary_sensor_window": EntityMeta(
        translation_key="window",
        unique_id_suffix="zone_{zone_id}_open_window",
        entity_category=None,
        icon=None,  # uses device_class
        legacy_name="Window",
    ),
    "binary_sensor_preheat_now": EntityMeta(
        translation_key="preheat_now",
        unique_id_suffix="zone_{zone_id}_preheat_now",
        entity_category="diagnostic",
        icon=None,  # uses device_class
        legacy_name="Preheat Now",
    ),
    "binary_sensor_window_predicted": EntityMeta(
        translation_key="window_predicted",
        unique_id_suffix="zone_{zone_id}_window_predicted",
        entity_category="diagnostic",
        icon=None,  # uses device_class
        legacy_name="Window Predicted",
    ),

    # ===================================================================
    # Buttons (button.py) — 6 entries
    # ===================================================================
    "button_resume_all": EntityMeta(
        translation_key="resume_all",
        unique_id_suffix="resume_all",  # hub-level
        entity_category=None,
        icon="mdi:calendar-refresh",
        legacy_name="Resume All",
    ),
    "button_refresh_ac": EntityMeta(
        translation_key="refresh_ac",
        unique_id_suffix="refresh_ac",  # hub-level
        entity_category="config",
        icon="mdi:air-conditioner",
        legacy_name="Refresh AC",
    ),
    "button_timer": EntityMeta(
        translation_key=None,  # uses dynamic _attr_name = f"{duration}min Timer"
        unique_id_suffix="zone_{zone_id}_timer_{duration}min",
        entity_category="config",
        icon="mdi:timer",
        legacy_name=None,
    ),
    "button_refresh_schedule": EntityMeta(
        translation_key="refresh_schedule",
        unique_id_suffix="zone_{zone_id}_refresh_schedule",
        entity_category=None,
        icon="mdi:calendar-refresh",
        legacy_name="Refresh Schedule",
    ),
    "button_boost": EntityMeta(
        translation_key="boost",
        unique_id_suffix="zone_{zone_id}_boost",
        entity_category=None,
        icon="mdi:fire",
        legacy_name="Boost",
    ),
    "button_smart_boost": EntityMeta(
        translation_key="smart_boost",
        unique_id_suffix="zone_{zone_id}_smart_boost",
        entity_category=None,
        icon="mdi:fire-alert",
        legacy_name="Smart Boost",
    ),
    # ===================================================================
    # Selects (select.py) — 3 hub-level entries
    # ===================================================================
    "select_presence_mode": EntityMeta(
        translation_key="presence_mode",
        unique_id_suffix="presence_mode",  # hub-level
        entity_category=None,  # intentional — user-facing control (D4)
        icon=None,
        legacy_name="Presence Mode",
    ),
    "select_overlay_mode": EntityMeta(
        translation_key="overlay_mode",
        unique_id_suffix="overlay_mode",  # hub-level
        entity_category="config",
        icon="mdi:timer-cog-outline",
        legacy_name="Overlay Mode",
    ),
    "select_timer_duration": EntityMeta(
        translation_key="timer_duration",
        unique_id_suffix="overlay_timer",  # hub-level
        entity_category="config",
        icon="mdi:timer",
        legacy_name="Overlay Timer",
    ),
    # ===================================================================
    # Switches (switch.py) — 4 entries (early_start, child_lock, test_mode, quota_reserve)
    # ===================================================================
    "switch_early_start": EntityMeta(
        translation_key="early_start",
        unique_id_suffix="zone_{zone_id}_early_start",
        entity_category="config",
        icon="mdi:clock-fast",
        legacy_name="Early Start",
    ),
    "switch_child_lock": EntityMeta(
        translation_key="child_lock",
        unique_id_suffix="device_{serial}_child_lock",
        entity_category="config",
        icon="mdi:lock",
        legacy_name="Child Lock",
    ),
    "switch_test_mode": EntityMeta(
        translation_key="test_mode",
        unique_id_suffix="test_mode_enabled",  # option_key used as suffix
        entity_category="config",
        icon=None,  # dynamic: mdi:test-tube / mdi:test-tube-off
        legacy_name="Test Mode",
    ),
    "switch_quota_reserve": EntityMeta(
        translation_key="quota_reserve",
        unique_id_suffix="quota_reserve_enabled",  # option_key used as suffix
        entity_category="config",
        icon=None,  # dynamic: mdi:shield-check / mdi:shield-off
        legacy_name="Quota Reserve",
    ),
    # ===================================================================
    # Climate (climate_heating.py, climate_ac.py) — 2 entries
    # ===================================================================
    "climate_heating": EntityMeta(
        translation_key="heating",
        unique_id_suffix="zone_{zone_id}_climate",
        entity_category=None,
        icon=None,  # uses device_class
        legacy_name=None,
    ),
    "climate_ac": EntityMeta(
        translation_key="ac",
        unique_id_suffix="zone_{zone_id}_ac_climate",
        entity_category=None,
        icon=None,  # uses device_class
        legacy_name=None,
    ),
    # ===================================================================
    # Water Heater (water_heater.py) — 1 entry
    # ===================================================================
    "water_heater_hot_water": EntityMeta(
        translation_key="hot_water",
        unique_id_suffix="zone_{zone_id}_water_heater",
        entity_category=None,
        icon=None,  # uses device_class
        legacy_name=None,
    ),
    # ===================================================================
    # Calendar (calendar.py) — 1 entry
    # ===================================================================
    "calendar_schedule": EntityMeta(
        translation_key="schedule",
        unique_id_suffix="zone_{zone_id}_schedule",
        entity_category=None,
        icon="mdi:calendar-clock",
        legacy_name="Schedule",
    ),
    # ===================================================================
    # Device Tracker (device_tracker.py) — 1 entry
    # ===================================================================
    "device_tracker_mobile": EntityMeta(
        translation_key=None,  # uses dynamic _attr_name = device_name
        unique_id_suffix="device_{device_id}",  # hub-level
        entity_category="diagnostic",
        icon=None,
        legacy_name=None,
    ),
    # ===================================================================
    # Bridge Sensors / Number (bridge API — flow temperature control)
    # ===================================================================
    "sensor_boiler_wiring_state": EntityMeta(
        translation_key="boiler_wiring_state",
        unique_id_suffix="boiler_wiring_state",
        entity_category="diagnostic",
        icon="mdi:pipe-wrench",
    ),
    "sensor_boiler_output_temperature": EntityMeta(
        translation_key="boiler_output_temperature",
        unique_id_suffix="boiler_output_temperature",
        entity_category="diagnostic",
        icon="mdi:thermometer-water",
    ),
    "number_boiler_max_output_temperature": EntityMeta(
        translation_key="boiler_max_output_temperature",
        unique_id_suffix="boiler_max_output_temperature",
        entity_category=None,
        icon="mdi:thermometer-water",
    ),
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_meta(key: str) -> EntityMeta:
    """Look up entity metadata by registry key.

    Raises KeyError if the key is not found.
    """
    return ENTITY_REGISTRY[key]


def get_entity_category(meta: EntityMeta) -> EntityCategory | None:
    """Resolve entity_category string to HA EntityCategory enum.

    Returns None when meta.entity_category is None.
    Import is deferred to avoid pulling HA at module level.
    """
    if meta.entity_category is None:
        return None
    from homeassistant.const import EntityCategory

    return EntityCategory(meta.entity_category)
