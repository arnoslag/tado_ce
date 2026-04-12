"""Tado CE diagnostics — config entry debug dump with PII redaction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import TadoConfigEntry

_LOGGER = logging.getLogger(__name__)

# Keys to redact from config entry data / coordinator data
TO_REDACT_CONFIG = {
    "home_id",
    "token",
    "refresh_token",
    "access_token",
    "username",
    "password",
    "email",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: TadoConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    # Redact sensitive fields from entry data and options
    redacted_entry_data = async_redact_data(dict(entry.data), TO_REDACT_CONFIG)
    redacted_options = async_redact_data(dict(entry.options), TO_REDACT_CONFIG)

    # Build coordinator data summary (redact PII from nested dicts)
    coord_data = coordinator.data or {}
    redacted_coord: dict[str, Any] = {}

    # Safe keys — no PII, include as-is
    for key in ("ratelimit", "weather", "offsets"):
        if key in coord_data:
            redacted_coord[key] = coord_data[key]

    # Zone count summary (don't dump full zone state)
    zones_info = coord_data.get("zones_info") or []
    redacted_coord["zones_info_count"] = len(zones_info)
    redacted_coord["zone_types"] = _summarise_zone_types(zones_info)

    # Config manager settings (no PII)
    config_summary = {}
    if coordinator.config_manager:
        config_summary = coordinator.config_manager.get_all_config()
    redacted_coord["config_settings"] = config_summary

    # Coordinator metadata
    redacted_coord["update_interval_seconds"] = (
        coordinator.update_interval.total_seconds() if coordinator.update_interval else None
    )
    redacted_coord["last_update_success"] = coordinator.last_update_success

    # State restore captured states (privacy-safe: no temperature values)
    sr_diagnostics = coordinator.get_state_restore_diagnostics()
    if sr_diagnostics:
        redacted_coord["state_restore_captured"] = sr_diagnostics

    # HomeKit diagnostics (redact credentials)
    homekit_diag: dict[str, Any] = {"status": "not_configured"}
    if coordinator.homekit_client is not None:
        client = coordinator.homekit_client
        if client.is_connected:
            homekit_diag["status"] = "connected"
        else:
            homekit_diag["status"] = "disconnected"
        mapped = len(getattr(client, "_zone_to_aids", {}))
        homekit_diag["mapped_zones"] = mapped
        from .const import HOMEKIT_CACHE_REFRESH_SECONDS, get_climate_zone_ids

        all_climate = get_climate_zone_ids(zones_info)
        homekit_diag["unmapped_zones"] = max(0, len(all_climate) - mapped)
        homekit_diag["cache_refresh_interval_seconds"] = HOMEKIT_CACHE_REFRESH_SECONDS
        # Check pairing file existence without exposing credentials
        from .const import get_data_file

        home_id = entry.data.get("home_id") or "default"
        pairing_path = get_data_file("homekit_pairing", home_id)
        homekit_diag["pairing_file_exists"] = pairing_path.exists()

    return {
        "entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "data": redacted_entry_data,
            "options": redacted_options,
        },
        "coordinator": redacted_coord,
        "homekit": homekit_diag,
    }


def _summarise_zone_types(zones_info: list[dict[str, Any]]) -> dict[str, int]:
    """Summarise zone types from zones_info list."""
    counts: dict[str, int] = {}
    for zone in zones_info:
        zone_type = zone.get("type", "UNKNOWN")
        counts[zone_type] = counts.get(zone_type, 0) + 1
    return counts
