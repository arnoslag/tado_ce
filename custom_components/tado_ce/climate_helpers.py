"""Climate helper functions.

Functions:
  update_offset(coordinator, zone_id) — reads temperature offset from cached file
  update_preset_mode(coordinator) — reads home/away presence from home_state.json
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def update_offset(
    coordinator: TadoDataUpdateCoordinator,
    zone_id: str,
) -> float | None:
    """Read temperature offset from cached offsets file.

    Returns the offset value if offset_enabled is True in config and data
    is available, otherwise None.

    Replaces inline _update_offset() in heating.py.

    Args:
        coordinator: The data update coordinator (provides config_manager, data_loader)
        zone_id: Zone ID to look up offset for

    Returns:
        Offset in °C, or None if disabled/unavailable

    """
    try:
        config_manager = coordinator.config_manager
        if not config_manager or not config_manager.get_offset_enabled():
            return None

        offsets = (coordinator.data or {}).get("offsets")
        if offsets:
            return offsets.get(zone_id)
        return None
    except Exception:  # noqa: BLE001, S110
        # Keep existing offset value on error — caller handles fallback
        return None


def update_preset_mode(coordinator: TadoDataUpdateCoordinator) -> str | None:
    """Read preset mode (HOME/AWAY) from home_state.json.

    Returns "home" or "away" (HA preset constants), or None if unavailable.

    Replaces inline _update_preset_mode() in heating.py.

    Args:
        coordinator: The data update coordinator (provides data_loader)

    Returns:
        PRESET_HOME or PRESET_AWAY string, or None if unavailable

    """
    from homeassistant.components.climate import PRESET_AWAY, PRESET_HOME

    try:
        home_state = (coordinator.data or {}).get("home_state")
        if home_state:
            presence = home_state.get("presence", "HOME")
            return PRESET_HOME if presence == "HOME" else PRESET_AWAY
    except Exception:  # noqa: BLE001, S110
        # Keep last known preset mode — caller handles fallback
        pass
    return None
