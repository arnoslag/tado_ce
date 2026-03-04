"""Shared helper functions for Tado CE entity actions.

Functions:
- check_bootstrap_reserve(): bootstrap reserve check before manual actions
- is_within_optimistic_window(): optimistic update window check
- record_smart_comfort_data(): smart comfort data recording for climate entities
"""
from __future__ import annotations

import logging
import time
from typing import Optional

_LOGGER = logging.getLogger(__name__)



async def check_bootstrap_reserve(hass, entity_name: str, entry_id: str = None) -> None:
    """Check bootstrap reserve and raise error if quota critically low.

    Bootstrap Reserve — blocks ALL actions when quota falls to the
    absolute minimum needed for auto-recovery after API reset.

    Extracted to action_helpers.py (was duplicated in 9 classes).
    Uses entry.runtime_data (coordinator).

    Args:
        hass: Home Assistant instance
        entity_name: Display name for error message
        entry_id: Optional config entry ID for per-entry lookup

    Raises:
        HomeAssistantError: If bootstrap reserve is depleted
    """
    from .ratelimit import async_check_bootstrap_reserve_or_raise
    coordinator = None
    if entry_id:
        try:
            config_entry = hass.config_entries.async_get_entry(entry_id)
            coordinator = config_entry.runtime_data if config_entry else None
        except (AttributeError, TypeError):
            pass
    await async_check_bootstrap_reserve_or_raise(hass, entity_name, coordinator=coordinator)



def is_within_optimistic_window(
    hass,
    optimistic_set_at: Optional[float],
    entry_id: str = None,
) -> bool:
    """Check if we're within the optimistic update window.

    Prevents stale API data from overwriting optimistic state.
    Extracted to action_helpers.py (was duplicated in 4 classes).
    Accepts entry_id for per-entry config lookup (H-1 fix).

    Args:
        hass: Home Assistant instance
        optimistic_set_at: Timestamp when optimistic state was set, or None
        entry_id: Optional config entry ID for per-entry lookup

    Returns:
        True if optimistic_set_at is set and elapsed time < optimistic window.
    """
    if optimistic_set_at is None:
        return False
    from .helpers import get_optimistic_window
    elapsed = time.time() - optimistic_set_at
    return elapsed < get_optimistic_window(hass, entry_id=entry_id) if hass else elapsed < 17.0



def record_smart_comfort_data(
    hass,
    zone_id: str,
    zone_name: str,
    current_temperature: Optional[float],
    target_temperature: Optional[float],
    is_active: bool,
    entry_id: str = None,
) -> None:
    """Record temperature data for Smart Comfort analytics.

    Records current temperature and heating/AC state to the
    SmartComfortManager for rate calculation and predictions.

    Extracted to action_helpers.py — unified heating + AC versions.
    Uses entry.runtime_data (coordinator).

    Args:
        hass: Home Assistant instance
        zone_id: Zone ID
        zone_name: Zone display name
        current_temperature: Current room temperature
        target_temperature: Target temperature
        is_active: Whether heating/AC is actively running
        entry_id: Optional config entry ID for per-entry lookup
    """
    try:
        smart_comfort_manager = None
        if entry_id:
            try:
                config_entry = hass.config_entries.async_get_entry(entry_id)
                coordinator = config_entry.runtime_data if config_entry else None
                if coordinator:
                    smart_comfort_manager = coordinator.smart_comfort_manager
            except (AttributeError, TypeError):
                pass
        if not smart_comfort_manager or not smart_comfort_manager.is_enabled:
            return

        if current_temperature is None:
            return

        smart_comfort_manager.record_temperature(
            zone_id=zone_id,
            zone_name=zone_name,
            temperature=current_temperature,
            is_heating=is_active,
            target_temperature=target_temperature,
        )
    except Exception as e:
        _LOGGER.debug("Failed to record smart comfort data for %s: %s", zone_name, e)

