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


async def api_call_with_rollback(
    entity,
    api_coro,
    *,
    hvac_mode,
    hvac_action,
    overlay_type: str | None = "MANUAL",
    target_temp: float | None = None,
    reason: str,
) -> bool:
    """Execute API call with optimistic update + rollback pattern.

    Consolidates the repeated pattern across climate_heating.py and climate_ac.py:
    1. Save old state
    2. Set optimistic state
    3. API call with timeout
    4. Success → log + trigger refresh
    5. Failure → rollback to old state

    Args:
        entity: Climate entity (heating or AC)
        api_coro: Awaitable API call (e.g., client.set_zone_overlay(...))
        hvac_mode: Target HVAC mode for optimistic update
        hvac_action: Target HVAC action for optimistic update
        overlay_type: Overlay type to set (None for AUTO/schedule mode)
        target_temp: Optional target temperature
        reason: Reason string for logging and refresh trigger

    Returns:
        True if API call succeeded, False otherwise

    """
    import asyncio

    from .helpers import async_trigger_immediate_refresh

    # Save old state for rollback
    old_mode = entity._attr_hvac_mode
    old_action = entity._attr_hvac_action
    old_overlay = entity._overlay_type

    # Optimistic update
    entity._attr_hvac_mode = hvac_mode
    entity._attr_hvac_action = hvac_action
    entity._overlay_type = overlay_type
    await entity._set_optimistic_state(hvac_mode, hvac_action, target_temp=target_temp)
    entity.async_write_ha_state()

    # API call with timeout
    api_success = False
    try:
        async with asyncio.timeout(10):
            api_success = await api_coro
    except TimeoutError:
        _LOGGER.warning("TIMEOUT: %s %s timed out", entity._zone_name, reason)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("ERROR: %s %s failed (%s)", entity._zone_name, reason, e)

    if api_success:
        _LOGGER.info("%s: %s", entity._zone_name, reason)
        await async_trigger_immediate_refresh(entity.hass, entity.entity_id, "hvac_mode_change")
    else:
        _LOGGER.warning("ROLLBACK: %s %s failed", entity._zone_name, reason)
        entity._attr_hvac_mode = old_mode
        entity._attr_hvac_action = old_action
        entity._overlay_type = old_overlay
        entity._clear_optimistic_state()
        entity.async_write_ha_state()

    return api_success
