"""Entity lifecycle cleanup for disabled feature toggles.

Handles removal of entities from the HA entity registry when users
disable feature toggles via the Options Flow UI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_registry import EntityRegistry

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature toggle → cleanup flag mapping
# Used by config_flow (detect transitions) and cleanup handler (execute).
# ---------------------------------------------------------------------------

FEATURE_CLEANUP_MAP: list[tuple[str, str, bool]] = [
    ("zone_configuration_enabled", "_cleanup_zone_config", True),
    ("thermal_analytics_enabled", "_cleanup_thermal_analytics", False),
    ("environment_sensors_enabled", "_cleanup_environment_sensors", True),
    ("zone_diagnostics_enabled", "_cleanup_zone_diagnostics", True),
    ("boost_buttons_enabled", "_cleanup_boost_buttons", True),
    ("device_controls_enabled", "_cleanup_device_controls", True),
    ("smart_comfort_enabled", "_cleanup_smart_comfort", False),
    ("schedule_calendar_enabled", "_cleanup_schedule_calendar", False),
    ("weather_enabled", "_cleanup_weather", False),
    ("mobile_devices_enabled", "_cleanup_mobile_devices", False),
]

# ---------------------------------------------------------------------------
# Cleanup definitions: flag → entity suffixes/patterns to remove
# ---------------------------------------------------------------------------

_CLEANUP_DEFINITIONS: dict[str, dict[str, Any]] = {
    "_cleanup_zone_config": {
        "label": "Zone Configuration",
        "prefix": "tado_ce_zone_",
        "suffixes": [
            "_heating_type", "_ufh_buffer", "_adaptive_preheat", "_smart_comfort_mode",
            "_window_type", "_overlay_mode", "_timer_duration", "_min_temp", "_max_temp", "_temp_offset",
        ],
    },
    "_cleanup_zone_diagnostics": {
        "label": "Zone Diagnostics",
        "prefix": "tado_ce_zone_",
        "suffixes": ["_battery", "_connection", "_heating", "_ac_power"],
        "extra_patterns": ["_battery", "_connection"],
    },
    "_cleanup_device_controls": {
        "label": "Device Controls",
        "patterns": ["_child_lock", "_early_start"],
    },
    "_cleanup_boost_buttons": {
        "label": "Boost Buttons",
        "patterns": ["_boost", "_smart_boost"],
    },
    "_cleanup_environment_sensors": {
        "label": "Environment Sensors",
        "prefix": "tado_ce_zone_",
        "suffixes": [
            "_mold_risk", "_comfort_level", "_condensation_risk",
            "_surface_temperature", "_dew_point", "_insights", "_window_predicted",
        ],
    },
    "_cleanup_thermal_analytics": {
        "label": "Thermal Analytics",
        "prefix": "tado_ce_zone_",
        "suffixes": [
            "_thermal_inertia", "_heating_rate", "_efficiency",
            "_approach_factor", "_historical_deviation", "_heating_cycles",
        ],
    },
    "_cleanup_smart_comfort": {
        "label": "Smart Comfort",
        "prefix": "tado_ce_zone_",
        "suffixes": [
            "_schedule_deviation", "_next_schedule_time", "_next_schedule_temp",
            "_preheat_advisor", "_smart_comfort_target", "_preheat_now",
        ],
        "extra_patterns": ["_preheat_now"],
    },
    "_cleanup_schedule_calendar": {
        "label": "Schedule Calendar",
        "exact_suffixes": ["_schedule", "_refresh_schedule"],
        "exclude_suffixes": ["_next_schedule", "_next_sched_temp", "_schedule_deviation"],
        "remove_device": "heating_schedule",
    },
    "_cleanup_weather": {
        "label": "Weather",
        "patterns": ["_outside_temp", "_solar_intensity", "_weather_state"],
    },
    "_cleanup_mobile_devices": {
        "label": "Mobile Devices",
        "match_contains": "_device_",
        "platform_filter": "device_tracker",
    },
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def cleanup_entities_by_suffix(
    entity_registry: EntityRegistry,
    domain: str,
    prefix: str,
    suffixes: list[str],
) -> int:
    """Remove entities matching prefix and any of the suffixes.

    Args:
        entity_registry: HA entity registry.
        domain: Integration domain (e.g., "tado_ce").
        prefix: unique_id prefix to match (e.g., "tado_ce_zone_").
        suffixes: List of suffixes to match (e.g., ["_battery", "_connection"]).

    Returns:
        Number of entities removed.
    """
    removed = 0
    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.platform != domain:
            continue
        unique_id = entity_entry.unique_id or ""
        if unique_id.startswith(prefix) and any(unique_id.endswith(suffix) for suffix in suffixes):
            _LOGGER.debug("  Removing entity: %s (unique_id: %s)", entity_id, unique_id)
            entity_registry.async_remove(entity_id)
            removed += 1
    return removed


def cleanup_entities_by_pattern(
    entity_registry: EntityRegistry,
    domain: str,
    suffixes: list[str],
) -> int:
    """Remove entities matching any of the suffixes (regardless of prefix).

    Args:
        entity_registry: HA entity registry.
        domain: Integration domain (e.g., "tado_ce").
        suffixes: List of suffixes to match (e.g., ["_child_lock", "_early_start"]).

    Returns:
        Number of entities removed.
    """
    removed = 0
    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.platform != domain:
            continue
        unique_id = entity_entry.unique_id or ""
        if unique_id.startswith("tado_ce_") and any(unique_id.endswith(suffix) for suffix in suffixes):
            _LOGGER.debug("  Removing entity: %s (unique_id: %s)", entity_id, unique_id)
            entity_registry.async_remove(entity_id)
            removed += 1
    return removed


def cleanup_entities_by_exact_suffix(
    entity_registry: EntityRegistry,
    domain: str,
    suffixes: list[str],
    exclude_suffixes: list[str] | None = None,
) -> int:
    """Remove entities matching suffixes but excluding false positives.

    Unlike cleanup_entities_by_pattern, this checks that the entity does NOT
    match any of the exclude_suffixes before removing. This prevents removing
    entities from other features that share a common suffix substring.

    Args:
        entity_registry: HA entity registry.
        domain: Integration domain (e.g., "tado_ce").
        suffixes: List of suffixes to match (e.g., ["_schedule"]).
        exclude_suffixes: Suffixes that should NOT be removed even if they
            match a suffix (e.g., ["_next_schedule"] to protect Smart Comfort).

    Returns:
        Number of entities removed.
    """
    excludes = exclude_suffixes or []
    removed = 0
    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.platform != domain:
            continue
        unique_id = entity_entry.unique_id or ""
        if not unique_id.startswith("tado_ce_"):
            continue
        if any(unique_id.endswith(exc) for exc in excludes):
            continue
        if any(unique_id.endswith(suffix) for suffix in suffixes):
            _LOGGER.debug("  Removing entity: %s (unique_id: %s)", entity_id, unique_id)
            entity_registry.async_remove(entity_id)
            removed += 1
    return removed


def cleanup_entities_by_contains(
    entity_registry: EntityRegistry,
    domain: str,
    contains: str,
    platform_filter: str | None = None,
) -> int:
    """Remove entities whose unique_id contains a substring.

    Optionally filters by HA platform domain (e.g., "device_tracker").

    Args:
        entity_registry: HA entity registry.
        domain: Integration domain (e.g., "tado_ce").
        contains: Substring to match in unique_id (e.g., "_device_").
        platform_filter: If set, only remove entities from this HA platform
            domain (e.g., "device_tracker"). Checked via entity_id prefix.

    Returns:
        Number of entities removed.
    """
    removed = 0
    for entity_id, entity_entry in list(entity_registry.entities.items()):
        if entity_entry.platform != domain:
            continue
        unique_id = entity_entry.unique_id or ""
        if not unique_id.startswith("tado_ce_"):
            continue
        if platform_filter and not entity_id.startswith(f"{platform_filter}."):
            continue
        if contains in unique_id:
            _LOGGER.debug("  Removing entity: %s (unique_id: %s)", entity_id, unique_id)
            entity_registry.async_remove(entity_id)
            removed += 1
    return removed


def cleanup_orphan_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device_suffix: str,
) -> bool:
    """Remove an orphan device from the device registry.

    Removes a device whose identifier matches tado_ce_{home_id}_{device_suffix}
    (or tado_ce_{device_suffix} for unknown home_id).

    Args:
        hass: Home Assistant instance.
        entry: Config entry owning the device.
        device_suffix: Suffix of the device identifier (e.g., "heating_schedule").

    Returns:
        True if a device was removed, False otherwise.
    """
    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)
    home_id = entry.data.get("home_id")

    if home_id:
        identifier = f"tado_ce_{home_id}_{device_suffix}"
    else:
        identifier = f"tado_ce_{device_suffix}"

    device_entry = device_registry.async_get_device(identifiers={(DOMAIN, identifier)})
    if device_entry:
        _LOGGER.info("  Removing orphan device: %s (identifier: %s)", device_entry.name, identifier)
        device_registry.async_remove_device(device_entry.id)
        return True
    return False


def cleanup_orphan_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> int:
    """Remove devices that have zero remaining entities after cleanup.

    Scans all devices belonging to this config entry and removes any
    that have no entities left in the entity registry. The hub device
    is protected and never removed.

    Args:
        hass: Home Assistant instance.
        entry: Config entry owning the devices.

    Returns:
        Number of orphan devices removed.
    """
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    home_id = entry.data.get("home_id")

    # Hub device identifier — never remove
    hub_identifier = f"tado_ce_hub_{home_id}" if home_id else "tado_ce_hub"

    removed = 0
    for device_entry in list(device_registry.devices.values()):
        # Only check devices belonging to this config entry
        if entry.entry_id not in device_entry.config_entries:
            continue

        # Protect hub device
        if (DOMAIN, hub_identifier) in device_entry.identifiers:
            continue

        # Check if device has any remaining entities
        device_entities = er.async_entries_for_device(
            entity_registry, device_entry.id, include_disabled_entities=True,
        )
        if not device_entities:
            _LOGGER.info(
                "  Removing orphan device: %s (id: %s, no remaining entities)",
                device_entry.name,
                device_entry.id,
            )
            device_registry.async_remove_device(device_entry.id)
            removed += 1

    return removed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_cleanup_flags(
    prev_options: dict[str, Any],
    new_options: dict[str, Any],
) -> dict[str, bool]:
    """Detect which feature toggles transitioned from enabled to disabled.

    Args:
        prev_options: Previous config entry options.
        new_options: New config entry options (from user input).

    Returns:
        Dict of cleanup flag name to True for each feature that was disabled.
    """
    flags: dict[str, bool] = {}
    for option_key, cleanup_flag, default in FEATURE_CLEANUP_MAP:
        was_enabled = prev_options.get(option_key, default)
        now_enabled = new_options.get(option_key, default)
        if was_enabled and not now_enabled:
            flags[cleanup_flag] = True
            _LOGGER.info("%s disabled: cleanup scheduled", option_key)
    return flags


def cleanup_disabled_feature_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> int:
    """Remove entities for features disabled via Options Flow.

    Reads pending cleanup flags from the coordinator and removes matching
    entities from the HA entity registry. Also removes orphan devices
    when a feature's dedicated device has no remaining entities.

    After all entity removals, performs a generic orphan device scan
    to remove ANY device that has zero remaining entities (not just
    devices with explicit ``remove_device`` definitions).

    Args:
        hass: Home Assistant instance.
        entry: Config entry being reloaded.

    Returns:
        Total number of entities removed.
    """
    from homeassistant.helpers import entity_registry as er

    entity_registry = er.async_get(hass)

    coordinator = getattr(entry, "runtime_data", None)
    pending = getattr(coordinator, "_pending_cleanup", {}) if coordinator else {}
    domain_data = pending.pop(entry.entry_id, {})
    total_removed = 0

    for flag, defn in _CLEANUP_DEFINITIONS.items():
        if not domain_data.get(flag, False):
            continue

        label = defn["label"]
        _LOGGER.info("Tado CE: %s disabled - removing entities", label)
        removed = 0

        if "suffixes" in defn:
            removed += cleanup_entities_by_suffix(
                entity_registry, DOMAIN, defn.get("prefix", ""), defn["suffixes"],
            )

        if "patterns" in defn:
            removed += cleanup_entities_by_pattern(entity_registry, DOMAIN, defn["patterns"])

        if "extra_patterns" in defn:
            removed += cleanup_entities_by_pattern(entity_registry, DOMAIN, defn["extra_patterns"])

        if "exact_suffixes" in defn:
            removed += cleanup_entities_by_exact_suffix(
                entity_registry, DOMAIN, defn["exact_suffixes"], defn.get("exclude_suffixes"),
            )

        if "match_contains" in defn:
            removed += cleanup_entities_by_contains(
                entity_registry, DOMAIN, defn["match_contains"], defn.get("platform_filter"),
            )

        total_removed += removed
        _LOGGER.info("  Removed %s %s entities", removed, label.lower())

        # Remove specific orphan device if defined (e.g., Heating Schedule device)
        if "remove_device" in defn:
            cleanup_orphan_device(hass, entry, defn["remove_device"])

    # Generic orphan device cleanup — remove ANY device with zero entities
    if total_removed > 0:
        orphan_count = cleanup_orphan_devices(hass, entry)
        if orphan_count:
            _LOGGER.info("Tado CE: Removed %s orphan device(s)", orphan_count)

    if total_removed > 0:
        _LOGGER.info("Tado CE: Total entities removed: %s", total_removed)

    return total_removed
