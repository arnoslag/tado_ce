"""Rate limit management for Tado CE.

This module handles API rate limit protection including:
- Bootstrap reserve checking (blocks all actions when quota critically low)
- Quota reserve protection (pauses polling to preserve manual operation quota)
- API limit notifications
- Reset time detection from HA history
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import aiofiles
import aiofiles.os

from .const import QUOTA_BOOTSTRAP_CALLS, get_data_file

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .config_manager import ConfigurationManager

_LOGGER = logging.getLogger(__name__)


def should_block_manual_action(ratelimit_data: dict, config_manager: ConfigurationManager) -> tuple[bool, str]:
    """Check if manual actions should be blocked due to bootstrap reserve.

    Bootstrap Reserve - blocks ALL actions (including manual) when quota
    falls to the absolute minimum needed for auto-recovery after API reset.

    Simplified - reads directly from ratelimit_data which already contains
    simulated values when Test Mode is ON (Single Source of Truth in ratelimit.json).

    Added quota_reserve_enabled check - allows users to disable protection.

    Args:
        ratelimit_data: Rate limit data with 'remaining', 'used', 'reset_seconds'
                        (already simulated when Test Mode is ON)
        config_manager: Configuration manager for feature settings

    Returns:
        Tuple of (should_block: bool, reason: str)
        - should_block: True if manual actions should be blocked
        - reason: Human-readable explanation (empty if not blocking)
    """
    # Check if Quota Reserve Protection is enabled
    if not config_manager.get_quota_reserve_enabled():
        _LOGGER.debug("Tado CE: Quota Reserve Protection disabled, not blocking manual actions")
        return False, ""

    # Check if reset time has passed - if so, allow actions to detect reset
    last_reset_utc = ratelimit_data.get("last_reset_utc")
    if last_reset_utc:
        try:
            last_reset = datetime.fromisoformat(last_reset_utc.replace('Z', '+00:00'))
            next_reset = last_reset + timedelta(hours=24)
            now_utc = datetime.now(timezone.utc)

            # If next reset time has passed, allow actions to detect actual reset
            if now_utc >= next_reset:
                return False, ""
        except Exception as e:
            _LOGGER.debug("Failed to check reset time: %s", e)

    # Read directly from ratelimit_data (already simulated when Test Mode ON)
    # No need to recalculate - save_ratelimit() stores the correct values
    remaining = ratelimit_data.get("remaining", 100)
    test_mode = ratelimit_data.get("test_mode", False)

    _LOGGER.debug(
        "Tado CE: should_block_manual_action check - remaining=%s, bootstrap_threshold=%s, test_mode=%s",
        remaining, QUOTA_BOOTSTRAP_CALLS, test_mode
    )

    # Check if we've hit the bootstrap reserve (hard limit)
    if remaining <= QUOTA_BOOTSTRAP_CALLS:
        reset_seconds = ratelimit_data.get("reset_seconds", 0)
        hours = reset_seconds // 3600
        minutes = (reset_seconds % 3600) // 60

        reason = (
            f"API limit reached ({remaining} calls remaining). "
            f"All actions blocked to preserve auto-recovery capability. "
            f"Use the Tado app for emergency changes. "
            f"Integration will auto-recover at reset in {hours}h {minutes}m."
        )
        return True, reason

    return False, ""



async def async_check_bootstrap_reserve(hass: HomeAssistant, coordinator=None) -> tuple[bool, str]:
    """Async helper to check bootstrap reserve for service handlers.

    Convenience wrapper that loads ratelimit data and config manager.
    Accepts coordinator (duck-typed — any object with
    .config_manager and .data_loader attributes).

    Args:
        hass: Home Assistant instance
        coordinator: Optional object with config_manager and data_loader attrs.

    Returns:
        Tuple of (should_block: bool, reason: str)
    """
    try:
        if coordinator is not None:
            config_manager = coordinator.config_manager
            ratelimit_data = await hass.async_add_executor_job(
                coordinator.data_loader.load_ratelimit_file
            )
        else:
            _LOGGER.debug("async_check_bootstrap_reserve called without coordinator, skipping check")
            return False, ""

        if not ratelimit_data:
            return False, ""

        return should_block_manual_action(ratelimit_data, config_manager)
    except Exception as e:
        _LOGGER.debug("Failed to check bootstrap reserve: %s", e)
        return False, ""



async def async_show_api_limit_notification(hass: HomeAssistant, message: str) -> None:
    """Show a persistent notification when API limit is reached.

    Persistent notification to inform user about API limit.

    Args:
        hass: Home Assistant instance
        message: Notification message
    """
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "Tado CE: API Limit Reached",
            "message": message + "\n\n**Tip:** Use the official Tado app for emergency temperature changes.",
            "notification_id": "tado_ce_api_limit",
        },
    )



async def async_check_bootstrap_reserve_or_raise(
    hass: HomeAssistant,
    entity_name: str = "",
    coordinator=None
) -> None:
    """Check bootstrap reserve and raise HomeAssistantError if quota critically low.

    DRY helper for all entities to check bootstrap reserve.
    Accepts coordinator instead of entry_data.

    Args:
        hass: Home Assistant instance
        entity_name: Optional entity name for logging (e.g., "Living Room", "Hot Water")
        coordinator: Optional object with config_manager and data_loader attrs.

    Raises:
        HomeAssistantError: If quota is at bootstrap reserve level
    """
    from homeassistant.exceptions import HomeAssistantError

    should_block, reason = await async_check_bootstrap_reserve(hass, coordinator=coordinator)
    if should_block:
        log_name = f" for {entity_name}" if entity_name else ""
        _LOGGER.warning("Tado CE: Blocking manual action%s - %s", log_name, reason)
        await async_show_api_limit_notification(hass, reason)
        raise HomeAssistantError(reason)



async def async_dismiss_api_limit_notification(hass: HomeAssistant) -> None:
    """Dismiss the API limit notification when quota is restored.

    Called when API reset is detected.

    Args:
        hass: Home Assistant instance
    """
    try:
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {
                "notification_id": "tado_ce_api_limit",
            },
        )
    except Exception:
        pass  # Notification may not exist


async def async_detect_reset_from_history(hass: HomeAssistant, home_id: str | None = None) -> datetime | None:
    """Detect API reset time from Home Assistant sensor history.

    Queries the recorder for the API usage sensor history and finds
    the time when the value dropped to its minimum (reset point).

    Args:
        hass: Home Assistant instance
        home_id: Home ID for multi-home support (finds correct entity via registry)

    Returns:
        Estimated reset time (datetime in UTC), or None if not enough data
    """
    try:
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states
        from homeassistant.helpers import entity_registry as er
        from homeassistant.util import dt as dt_util

        # Query last 36 hours of history (to catch reset even if it was yesterday)
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(hours=36)

        # Find correct entity_id via unique_id (multi-home safe)
        entity_id = None
        if home_id:
            target_uid = f"tado_ce_{home_id}_api_usage"
            registry = er.async_get(hass)
            entry = registry.async_get_entity_id("sensor", "tado_ce", target_uid)
            if entry:
                entity_id = entry

        # Fallback to hardcoded entity_id (single-home or registry miss)
        if not entity_id:
            entity_id = "sensor.tado_ce_api_usage"

        # Get history from recorder
        def _get_history():
            return get_significant_states(
                hass,
                start_time,
                end_time,
                [entity_id],
                significant_changes_only=False
            )

        states = await get_instance(hass).async_add_executor_job(_get_history)

        if not states or entity_id not in states:
            _LOGGER.debug("HA History Detection: No history found for sensor.tado_ce_api_usage")
            return None

        history = states[entity_id]
        if len(history) < 10:
            _LOGGER.debug("HA History Detection: Not enough history points (%s)", len(history))
            return None

        # Parse states and find minimum value (reset point)
        # The reset is when value drops from high to low
        min_value = float('inf')
        min_time = None
        prev_value = None

        for state in history:
            try:
                value = int(state.state)
                state_time = state.last_changed

                # Detect reset: value dropped significantly (>50% drop or to <10)
                if prev_value is not None and prev_value > 50:
                    if value < prev_value * 0.2 or value < 10:
                        # This is likely the reset point
                        _LOGGER.debug(
                            "HA History Detection: Reset detected! %s -> %s at %s",
                            prev_value, value, state_time
                        )
                        return state_time.replace(tzinfo=timezone.utc) if state_time.tzinfo is None else state_time

                # Track minimum as fallback
                if value < min_value:
                    min_value = value
                    min_time = state_time

                prev_value = value

            except (ValueError, TypeError):
                continue

        # If no clear reset detected, use minimum value time
        if min_time and min_value < 20:
            _LOGGER.debug("HA History Detection: Using minimum value as reset: %s at %s", min_value, min_time)
            return min_time.replace(tzinfo=timezone.utc) if min_time.tzinfo is None else min_time

        _LOGGER.debug("HA History Detection: Could not detect reset (min_value=%s)", min_value)
        return None

    except ImportError:
        _LOGGER.debug("Recorder component not available")
        return None
    except Exception as e:
        _LOGGER.debug("Failed to detect reset from history: %s", e)
        return None


async def async_update_ratelimit_reset_time(
    hass: HomeAssistant, detected_reset: datetime, home_id: str | None = None,
) -> None:
    """Update ratelimit JSON with detected reset time from HA history.

    This is called after sync when we detect the actual reset time from
    the API usage sensor history. It's more accurate than extrapolation.

    Args:
        hass: Home Assistant instance
        detected_reset: Detected reset time (datetime in UTC)
        home_id: Home ID for per-home ratelimit file (multi-home support)
    """
    try:
        ratelimit_path = get_data_file("ratelimit", home_id)
        if not await aiofiles.os.path.exists(ratelimit_path):
            return

        async with aiofiles.open(ratelimit_path, 'r') as f:
            content = await f.read()
            data = json.loads(content)

        # Only update if detected time is different from stored time
        current_reset = data.get("last_reset_utc")
        new_reset = detected_reset.strftime("%Y-%m-%dT%H:%M:%SZ")

        if current_reset != new_reset:
            data["last_reset_utc"] = new_reset

            # Recalculate reset_seconds, reset_at, reset_human
            now_utc = datetime.now(timezone.utc)
            next_reset = detected_reset + timedelta(hours=24)

            # If next_reset is in the past, add another 24h
            while next_reset <= now_utc:
                next_reset += timedelta(hours=24)

            seconds_until_reset = int((next_reset - now_utc).total_seconds())

            if seconds_until_reset > 0:
                hours = seconds_until_reset // 3600
                minutes = (seconds_until_reset % 3600) // 60
                data["reset_seconds"] = seconds_until_reset
                data["reset_at"] = next_reset.isoformat()
                data["reset_human"] = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"

            # Write back with atomic write
            temp_path = ratelimit_path.with_suffix('.tmp')
            async with aiofiles.open(temp_path, 'w') as f:
                await f.write(json.dumps(data, indent=2))

            await aiofiles.os.replace(temp_path, ratelimit_path)
            _LOGGER.info("Updated reset time from HA history: %s UTC", detected_reset.strftime('%H:%M'))

    except Exception as e:
        _LOGGER.debug("Failed to update ratelimit reset time: %s", e)
