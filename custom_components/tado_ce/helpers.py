"""Helper functions for Tado CE.

This module contains shared helper functions used across multiple entities:
- Immediate refresh triggering
- Optimistic update window calculation
- Overlay termination configuration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _get_coordinator(hass: HomeAssistant, entry_id: str):
    """Get coordinator from entry_id, or None."""
    try:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and hasattr(entry, 'runtime_data') and entry.runtime_data is not None:
            return entry.runtime_data
    except (AttributeError, TypeError):
        pass
    return None



async def async_trigger_immediate_refresh(  # noqa: PLR0913
    hass: HomeAssistant,
    entity_id: str,
    reason: str,
    force: bool = False,  # noqa: FBT001, FBT002
    skip_debounce: bool = False,  # noqa: FBT001, FBT002
    include_home_state: bool = False,  # noqa: FBT001, FBT002
) -> None:
    """Trigger immediate refresh after state change.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID that triggered the refresh
        reason: Reason for the refresh (for logging)
        force: If True, force refresh even if recently refreshed (for buttons)
        skip_debounce: If True, skip debounce delay (for buttons)
        include_home_state: If True, also fetch home state (for presence mode changes)

    """
    try:
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

        entity_registry = er.async_get(hass)
        entity_entry = entity_registry.async_get(entity_id)
        if entity_entry and entity_entry.config_entry_id:
            coordinator = _get_coordinator(hass, entity_entry.config_entry_id)
            if coordinator and coordinator.refresh_handler:
                    await coordinator.refresh_handler.trigger_refresh(
                        entity_id, reason, force=force,
                        skip_debounce=skip_debounce,
                        include_home_state=include_home_state,
                    )
                    return
        _LOGGER.warning("No refresh handler found for entity %s", entity_id)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to trigger immediate refresh: %s", e)




def get_optimistic_window(hass: HomeAssistant, entry_id: str | None = None) -> float:
    """Get the optimistic update window duration in seconds.

    The optimistic window = debounce_seconds + 2.0 seconds buffer.
    During this window, entities ignore API updates to preserve optimistic state.

    Args:
        hass: Home Assistant instance
        entry_id: Optional config entry ID for per-entry config lookup

    Returns:
        Optimistic window duration in seconds (default: 17.0 = 15 + 2)

    """
    try:
        if entry_id:
            coordinator = _get_coordinator(hass, entry_id)
            if coordinator and coordinator.config_manager:
                return float(coordinator.config_manager.get_refresh_debounce_seconds()) + 2.0
    except Exception:  # noqa: BLE001, S110
        pass
    return 17.0  # Default: 15s debounce + 2s buffer




def get_overlay_termination(hass: HomeAssistant, entry_id: str | None = None) -> dict:
    """Get the termination dict for overlay API calls.

    Args:
        hass: Home Assistant instance
        entry_id: Optional config entry ID for per-entry lookup

    Returns:
        {"type": "TADO_MODE"} or {"type": "MANUAL"} or {"type": "TIMER", "durationInSeconds": ...}
        Note: Tado API only accepts MANUAL, TADO_MODE, TIMER (not NEXT_TIME_BLOCK)

    """
    mode = "TADO_MODE"
    duration = 60
    if entry_id:
        try:
            coordinator = _get_coordinator(hass, entry_id)
            if coordinator:
                mode = coordinator.overlay_mode or "TADO_MODE"
                duration = coordinator.timer_duration or 60
        except (AttributeError, TypeError):
            pass

    # Map internal storage values to API-accepted values
    # Tado API only accepts: MANUAL, TADO_MODE, TIMER
    if mode == "NEXT_TIME_BLOCK":
        mode = "TADO_MODE"

    if mode == "TIMER":
        return {"type": "TIMER", "durationInSeconds": duration * 60}

    return {"type": mode}




def get_zone_overlay_termination(hass: HomeAssistant, zone_id: str, entry_id: str | None = None) -> dict:
    """Get the termination dict for overlay API calls with per-zone support.

    Priority:
    1. Per-zone overlay_mode (if zone_config_manager available and zone has override)
    2. Global overlay_mode (from coordinator)

    Args:
        hass: Home Assistant instance
        zone_id: Zone ID to get overlay mode for
        entry_id: Optional config entry ID for per-entry lookup

    Returns:
        {"type": "..."} or {"type": "...", "durationInSeconds": ...} for Timer mode

    """
    zone_config_manager = None
    if entry_id:
        try:
            coordinator = _get_coordinator(hass, entry_id)
            if coordinator:
                zone_config_manager = coordinator.zone_config_manager
        except (AttributeError, TypeError):
            pass

    if zone_config_manager:
        # Get per-zone overlay mode (UPPERCASE values)
        zone_mode = zone_config_manager.get_zone_value(zone_id, "overlay_mode", None)

        if zone_mode and zone_mode != "TADO_MODE":
            # Map to API values
            # Note: Tado API only accepts MANUAL, TADO_MODE, TIMER
            # NEXT_TIME_BLOCK maps to TADO_MODE which follows device settings
            mode_map = {
                "NEXT_TIME_BLOCK": "TADO_MODE",  # API doesn't accept NEXT_TIME_BLOCK
                "TIMER": "TIMER",
                "MANUAL": "MANUAL",
            }
            api_mode = mode_map.get(zone_mode, "TADO_MODE")

            # Handle Timer mode with duration
            if api_mode == "TIMER":
                duration = zone_config_manager.get_zone_value(zone_id, "timer_duration", 60)
                return {"type": "TIMER", "durationInSeconds": duration * 60}

            return {"type": api_mode}

    # Fallback to global overlay mode (handles TADO_MODE and when no per-zone config)
    return get_overlay_termination(hass, entry_id=entry_id)



def build_timer_termination(
    duration_minutes: int | None = None,
    overlay: str | None = None,
    hass: HomeAssistant = None,
    zone_id: str | None = None,
    entry_id: str | None = None,
) -> dict:
    """Build termination dict for set_timer / set_overlay calls.

    Consolidates the duplicated termination-building logic from:
    - TadoClimate.async_set_timer (heating.py)
    - TadoACClimate.async_set_timer (ac.py)
    - TadoACClimate._async_set_ac_overlay (ac.py)

    Priority:
    1. If duration_minutes provided → TIMER termination
    2. If overlay == 'next_time_block' → TADO_MODE termination
    3. If overlay == 'manual' → MANUAL termination
    4. Otherwise → per-zone overlay termination (from config)

    Args:
        duration_minutes: Timer duration in minutes (takes highest priority)
        overlay: Overlay type string ('next_time_block', 'manual', or None)
        hass: Home Assistant instance (needed for per-zone config fallback)
        zone_id: Zone ID (needed for per-zone config fallback)
        entry_id: Config entry ID (needed for per-zone config fallback)

    Returns:
        Termination dict for Tado API, e.g. {"type": "TIMER", "durationInSeconds": 3600}

    """
    if duration_minutes:
        return {"type": "TIMER", "durationInSeconds": duration_minutes * 60}

    if overlay:
        overlay_upper = overlay.upper()
        if overlay_upper == "NEXT_TIME_BLOCK":
            return {"type": "TADO_MODE"}
        if overlay_upper == "MANUAL":
            return {"type": "MANUAL"}

    # Fall back to per-zone / global overlay config
    if hass and zone_id:
        return get_zone_overlay_termination(hass, zone_id, entry_id=entry_id)
    if hass:
        return get_overlay_termination(hass, entry_id=entry_id)

    # Ultimate fallback
    return {"type": "MANUAL"}
