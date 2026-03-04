"""Device Manager for Tado CE Integration.

This module manages device creation and entity assignment for the Tado CE integration.
It provides functions to generate device info for both the hub device and individual zone devices.

CRITICAL: This module must be called from async context with proper executor handling.
The load_version() function performs blocking I/O and should be
called via hass.async_add_executor_job() during integration setup.
"""
import json
import logging
from functools import lru_cache
from pathlib import Path

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_version() -> str:
    """Load version from manifest.json (blocking I/O, cached after first call).

    This function performs blocking file I/O and MUST be called via
    hass.async_add_executor_job() from async context during integration setup.

    Returns:
        str: The version string, or "unknown" if not available.
    """
    try:
        manifest_path = Path(__file__).parent / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)
            return manifest.get("version", "unknown")
    except Exception as e:
        _LOGGER.warning("Failed to load version from manifest: %s", e)
        return "unknown"


def _get_cached_version() -> str:
    """Get cached version.

    Returns the version if already loaded via load_version(),
    otherwise returns "unknown".

    Returns:
        str: The cached version, or "unknown" if not loaded.
    """
    if load_version.cache_info().currsize == 0:
        return "unknown"
    return load_version()


def get_hub_device_info(home_id: str) -> DeviceInfo:
    """Get device info for Tado CE Hub.

    The hub device contains global entities that apply to the entire Tado system,
    such as API usage sensors, weather sensors, and mobile device trackers.

    Hub identifier now includes home_id for multi-home support.
    Format: tado_ce_hub_{home_id}

    Args:
        home_id: The home ID (required).

    Returns:
        DeviceInfo: Device information for the Tado CE Hub.
    """
    identifier = f"tado_ce_hub_{home_id}" if home_id != "unknown" else "tado_ce_hub"

    return DeviceInfo(
        configuration_url="https://app.tado.com",
        identifiers={(DOMAIN, identifier)},
        name="Tado CE Hub",
        manufacturer=MANUFACTURER,
        model="Tado CE Integration",
        sw_version=_get_cached_version(),
    )


def get_zone_device_info(zone_id: str, zone_name: str, zone_type: str, home_id: str) -> DeviceInfo:
    """Get device info for a specific Tado zone.

    Each zone device represents a physical zone (room) in the Tado system and contains
    all entities specific to that zone (climate, sensors, switches, etc.).

    Zone identifier now includes home_id for multi-home support.
    Format: tado_ce_{home_id}_zone_{zone_id}

    Args:
        zone_id: The unique identifier for the zone (e.g., "1", "4", "9").
        zone_name: The human-readable name of the zone (e.g., "Living Room").
        zone_type: The type of zone - "HEATING", "AIR_CONDITIONING", or "HOT_WATER".
        home_id: The home ID (required).

    Returns:
        DeviceInfo: Device information for the zone device.
    """
    model = get_zone_type_display(zone_type)

    # Include home_id in identifiers for multi-home support
    if home_id != "unknown":
        zone_identifier = f"tado_ce_{home_id}_zone_{zone_id}"
        hub_identifier = f"tado_ce_hub_{home_id}"
    else:
        zone_identifier = f"tado_ce_zone_{zone_id}"
        hub_identifier = "tado_ce_hub"

    return DeviceInfo(
        configuration_url=f"https://app.tado.com/en/main/home/zoneV2/{zone_id}",
        identifiers={(DOMAIN, zone_identifier)},
        name=zone_name,
        manufacturer=MANUFACTURER,
        model=model,
        suggested_area=zone_name,
        via_device=(DOMAIN, hub_identifier),
    )


def get_zone_type_display(zone_type: str) -> str:
    """Convert zone type to display name for device model field.

    Args:
        zone_type: The zone type from Tado API - "HEATING", "AIR_CONDITIONING", or "HOT_WATER".

    Returns:
        str: Human-readable display name for the zone type.
    """
    zone_type_map = {
        "HEATING": "Heating Zone",
        "AIR_CONDITIONING": "AC Zone",
        "HOT_WATER": "Hot Water Zone",
    }
    return zone_type_map.get(zone_type, "Unknown Zone")


def get_device_name_suffix(zone_id: str, device_serial: str, device_type: str, zones_info: list) -> str:
    """Get device name suffix for zones with multiple devices.

    When a zone has multiple physical devices (e.g., 1 sensor + 2 valves), entity names
    need to be differentiated. This function generates an appropriate suffix.

    Args:
        zone_id: The zone ID (e.g., "1", "4").
        device_serial: The device serial number (e.g., "RU1234567").
        device_type: The device type (e.g., "VA02", "RU01").
        zones_info: The full zones_info data from zones_info.json.

    Returns:
        str: Empty string if zone has only 1 device, otherwise a suffix like " VA02 (1)" or " RU01".

    Examples:
        - Single device zone: "" (no suffix)
        - Multiple devices, different types: " VA02", " RU01"
        - Multiple devices, same type: " VA02 (1)", " VA02 (2)"
    """
    # Find the zone
    zone = next((z for z in zones_info if str(z.get('id')) == str(zone_id)), None)
    if not zone:
        return ""

    devices = zone.get('devices', [])
    if len(devices) <= 1:
        return ""  # Single device - no suffix needed

    # Multiple devices - check if there are multiple of the same type
    same_type_devices = [d for d in devices if d.get('deviceType') == device_type]

    if len(same_type_devices) > 1:
        # Multiple devices of same type - add index
        try:
            index = next(i + 1 for i, d in enumerate(same_type_devices) if d.get('shortSerialNo') == device_serial)
            return f" {device_type} ({index})"
        except StopIteration:
            return f" {device_type}"
    else:
        # Only one of this type - just add device type
        return f" {device_type}"
