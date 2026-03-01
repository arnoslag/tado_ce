"""Shared helper functions for Tado CE entity actions.

v3.0.0: DRY consolidation — extracted from climate.py, button.py, select.py,
switch.py, water_heater.py to eliminate duplicate methods.

Functions:
- check_bootstrap_reserve(): was duplicated in 9 entity classes
- is_within_optimistic_window(): was duplicated in 4 entity classes
- record_smart_comfort_data(): was duplicated in 2 climate classes
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def check_bootstrap_reserve(hass, entity_name: str) -> None:
    """Check bootstrap reserve and raise error if quota critically low.

    v2.0.1: Bootstrap Reserve — blocks ALL actions when quota falls to the
    absolute minimum needed for auto-recovery after API reset.

    v3.0.0: Extracted to action_helpers.py (was duplicated in 9 classes).

    Args:
        hass: Home Assistant instance
        entity_name: Display name for error message

    Raises:
        HomeAssistantError: If bootstrap reserve is depleted
    """
    from . import async_check_bootstrap_reserve_or_raise
    await async_check_bootstrap_reserve_or_raise(hass, entity_name)


def is_within_optimistic_window(
    hass,
    optimistic_set_at: Optional[float],
) -> bool:
    """Check if we're within the optimistic update window.

    v1.9.6: Prevents stale API data from overwriting optimistic state.
    v3.0.0: Extracted to action_helpers.py (was duplicated in 4 classes).

    Args:
        hass: Home Assistant instance
        optimistic_set_at: Timestamp when optimistic state was set, or None

    Returns:
        True if optimistic_set_at is set and elapsed time < optimistic window.
    """
    if optimistic_set_at is None:
        return False
    from . import get_optimistic_window
    elapsed = time.time() - optimistic_set_at
    return elapsed < get_optimistic_window(hass) if hass else elapsed < 17.0


def record_smart_comfort_data(
    hass,
    zone_id: str,
    zone_name: str,
    current_temperature: Optional[float],
    target_temperature: Optional[float],
    is_active: bool,
) -> None:
    """Record temperature data for Smart Comfort analytics.

    v1.9.0: Records current temperature and heating/AC state to the
    SmartComfortManager for rate calculation and predictions.

    v3.0.0: Extracted to action_helpers.py — unified heating + AC versions.
    For heating zones, is_active = heating_power > 0.
    For AC zones, is_active = ac_power_value == 'ON'.

    Args:
        hass: Home Assistant instance
        zone_id: Zone ID
        zone_name: Zone display name
        current_temperature: Current room temperature
        target_temperature: Target temperature
        is_active: Whether heating/AC is actively running
    """
    try:
        smart_comfort_manager = hass.data.get(DOMAIN, {}).get('smart_comfort_manager')
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
