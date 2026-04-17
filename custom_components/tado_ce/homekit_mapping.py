"""Tado CE HomeKit Mapping — serial number to zone ID mapping."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .homekit_client import CHAR_MODEL, CHAR_SERIAL_NUMBER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Bridge model identifier — skip in mapping (not a zone device)
_BRIDGE_MODEL: str = "IB01"

_STORE_VERSION = 1


def build_serial_mapping(
    accessories: list[dict[str, Any]],
    cloud_zones_info: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map HomeKit accessory serials to Tado zone IDs.

    Strategy:
    1. Extract serial from each HomeKit accessory (characteristic 0x30)
    2. Extract device serials from cloud API zone info
    3. Match by serial number (exact match)
    4. Skip bridge accessory (model IB01)

    Returns:
        {"serial_to_zone": {...}, "zone_to_aids": {...}, "last_updated": "..."}
    """
    empty_result: dict[str, Any] = {
        "serial_to_zone": {},
        "zone_to_aids": {},
        "last_updated": dt_util.utcnow().isoformat(),
    }

    if not accessories:
        _LOGGER.warning("HomeKit: No accessories found, cannot build mapping")
        return empty_result

    if not cloud_zones_info:
        _LOGGER.warning("HomeKit: No cloud zone info, cannot build mapping")
        return empty_result

    # Cloud: zone_id → set of device serials
    zone_serials: dict[str, set[str]] = {}
    for zone in cloud_zones_info:
        raw_id = zone.get("id")
        if not raw_id:  # Skip None, 0, "", False — Tado zone IDs start from 1
            _LOGGER.debug("HomeKit: Skipping zone with invalid id: %s", raw_id)
            continue
        zone_id = str(raw_id)
        devices = zone.get("devices") or []
        zone_serials[zone_id] = {d.get("serialNo", "") for d in devices} - {""}

    _LOGGER.debug(
        "HomeKit: Cloud zone serials: %s",
        {zid: len(serials) for zid, serials in zone_serials.items()},
    )

    # HomeKit: extract serial and model per accessory
    serial_to_zone: dict[str, str] = {}
    zone_to_aids: dict[str, list[int]] = {}

    for acc in accessories:
        aid: int | None = acc.get("aid")
        serial = model = None
        for svc in acc.get("services", []):
            for char in svc.get("characteristics", []):
                # aiohomekit normalizes types to full UUID: 0000XXXX-0000-1000-8000-0026BB765291
                # Extract short form by taking chars [4:8] or stripping the base UUID suffix
                raw_type = char.get("type", "")
                if "-" in raw_type:
                    # Full UUID — extract short form (hex digits before first dash, strip leading zeros)
                    ctype = raw_type.split("-")[0].lstrip("0").upper()
                else:
                    ctype = raw_type.upper().lstrip("0")
                if ctype == CHAR_SERIAL_NUMBER.upper():
                    serial = char.get("value")
                elif ctype == CHAR_MODEL.upper():
                    model = char.get("value")

        # Skip bridge accessory
        if model == _BRIDGE_MODEL:
            _LOGGER.debug("HomeKit: Skipping bridge accessory (IB01)")
            continue

        if not serial or aid is None:
            _LOGGER.debug("HomeKit: Accessory aid=%s has no serial, skipping", aid)
            continue

        # Match serial to zone
        matched = False
        for zone_id, serials in zone_serials.items():
            if serial in serials:
                serial_to_zone[serial] = zone_id
                zone_to_aids.setdefault(zone_id, []).append(aid)
                matched = True
                break

        if not matched:
            _LOGGER.warning(
                "HomeKit: Accessory serial %s not found in any cloud zone",
                serial,
            )

    _LOGGER.info(
        "HomeKit: Mapped %d accessories to %d zones",
        len(serial_to_zone),
        len(zone_to_aids),
    )

    return {
        "serial_to_zone": serial_to_zone,
        "zone_to_aids": zone_to_aids,
        "last_updated": dt_util.utcnow().isoformat(),
    }


def validate_mapping(
    mapping: dict[str, Any],
    valid_zone_ids: set[str] | None = None,
) -> bool:
    """Validate a device mapping for integrity.

    Checks:
    - No zone "0" entries (invalid Tado zone ID)
    - If valid_zone_ids provided, all mapped zones must be in the set

    Args:
        mapping: Device mapping dict with serial_to_zone and zone_to_aids.
        valid_zone_ids: Optional set of known-good zone IDs from cloud API.

    Returns:
        True if mapping is valid, False if it should be rebuilt.
    """
    serial_to_zone = mapping.get("serial_to_zone", {})
    zone_to_aids = mapping.get("zone_to_aids", {})

    # Check for zone "0" — known corruption from earlier builds
    if "0" in zone_to_aids or "0" in serial_to_zone.values():
        _LOGGER.warning("HomeKit: Cached mapping contains invalid zone '0' — forcing rebuild")
        return False

    # Cross-check against cloud zone IDs if available
    if valid_zone_ids is not None:
        mapped_zone_ids = set(serial_to_zone.values())
        invalid_zones = mapped_zone_ids - valid_zone_ids
        if invalid_zones:
            _LOGGER.warning(
                "HomeKit: Cached mapping contains zone IDs not in cloud: %s — forcing rebuild",
                invalid_zones,
            )
            return False

    return True


async def load_device_mapping(
    hass: HomeAssistant,
    home_id: str,
) -> dict[str, Any] | None:
    """Load stored device mapping from HA Store.

    Returns:
        Mapping dict or None if not found.
    """
    store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, f"tado_ce/homekit_device_map_{home_id}")
    data = await store.async_load()
    if data and isinstance(data, dict):
        return data

    # Try migrating from old JSON file
    from .const import get_data_file
    from .storage import async_migrate_json_to_store

    old_path = get_data_file("homekit_device_map", home_id)
    migrated = await async_migrate_json_to_store(hass, old_path, store, label="homekit_device_map")
    if migrated and isinstance(migrated, dict):
        return migrated
    return None


async def save_device_mapping(
    hass: HomeAssistant,
    home_id: str,
    mapping: dict[str, Any],
) -> None:
    """Save device mapping to HA Store."""
    store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, f"tado_ce/homekit_device_map_{home_id}")
    await store.async_save(mapping)
    _LOGGER.debug("HomeKit: Saved device mapping for home %s", home_id)


async def remove_device_mapping(
    hass: HomeAssistant,
    home_id: str,
) -> None:
    """Remove device mapping from HA Store."""
    store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, f"tado_ce/homekit_device_map_{home_id}")
    await store.async_remove()
    _LOGGER.debug("HomeKit: Removed device mapping for home %s", home_id)
