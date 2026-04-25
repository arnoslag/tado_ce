"""Tado CE shared helpers — retry delay, datetime parsing, overlay termination, refresh trigger."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
import logging
import random
from typing import TYPE_CHECKING, Any

from .const import MAX_RETRY_ATTEMPTS, MAX_RETRY_DELAY, OVERLAY_MODE_DEFAULT, RETRY_BASE_DELAY, TIMER_DURATION_DEFAULT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import TadoDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Serial number masking — keep prefix + first few chars for debugging, mask the rest.
# Bridge serials (IB...) are especially sensitive: combined with the 4-digit auth
# code printed on the bridge, a full serial in shared logs enables brute-force.
_SERIAL_VISIBLE_CHARS: int = 6


def mask_serial(serial: str) -> str:
    """Mask a device or bridge serial for safe logging.

    Keeps the first few characters visible for debugging (e.g. 'VA0315...',
    'IB0123...') and replaces the rest with '…'.
    """
    if not serial or len(serial) <= _SERIAL_VISIBLE_CHARS:
        return serial
    return serial[:_SERIAL_VISIBLE_CHARS] + "…"


def mask_serial_dict(d: dict[str, str]) -> dict[str, str]:
    """Mask all keys (serials) in a serial-to-zone mapping dict."""
    return {mask_serial(k): v for k, v in d.items()}


def get_zone_states(coord_data: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Extract zone states dict from coordinator data.

    Handles all null-safety: None coord_data, missing "zones" key,
    missing "zoneStates" key.

    Returns:
        Dict mapping zone_id -> zone_state_dict, or empty dict.
    """
    if not coord_data:
        return {}
    zones = coord_data.get("zones")
    if not isinstance(zones, dict):
        return {}
    return zones.get("zoneStates") or {}


def get_zone_state(coord_data: dict[str, Any] | None, zone_id: str) -> dict[str, Any] | None:
    """Get state for a single zone from coordinator data.

    Convenience wrapper: get_zone_states(data).get(zone_id).
    """
    return get_zone_states(coord_data).get(zone_id)


def merge_homekit_into_zone_data(
    zone_data: dict[str, Any],
    zone_id: str,
    coordinator: TadoDataUpdateCoordinator,
) -> dict[str, Any]:
    """Overlay fresh HomeKit temperature onto cloud zone data.

    Returns a shallow copy of zone_data with sensorDataPoints merged.
    Temperature uses HomeKit when fresh (real-time, accurate).
    Humidity always uses cloud (bridge humidity is stale/unreliable).
    If HomeKit is not connected or has no fresh data, returns zone_data unchanged.

    Safe to call from any entity regardless of base class.
    """
    try:
        provider = coordinator.homekit_provider
        reconciler = coordinator.state_reconciler
        if provider is None or reconciler is None:
            return zone_data
        if not provider.is_connected:
            return zone_data
        reconciler.local_provider = provider
        sensor_data = (zone_data.get("sensorDataPoints") or {}).copy()
        cloud_temp = (sensor_data.get("insideTemperature") or {}).get("celsius")
        cloud_humidity = (sensor_data.get("humidity") or {}).get("percentage")
        merged_temp, temp_src = reconciler.merge_zone_temperature(zone_id, cloud_temp)
        merged_hum, hum_src = reconciler.merge_zone_humidity(zone_id, cloud_humidity)
        if merged_temp is not None:
            sensor_data.setdefault("insideTemperature", {})["celsius"] = merged_temp
        if merged_hum is not None:
            sensor_data.setdefault("humidity", {})["percentage"] = merged_hum
        # Log when merge changes the value (cloud → homekit or vice versa)
        if cloud_temp != merged_temp or cloud_humidity != merged_hum:
            _LOGGER.debug(
                "Zone %s merge: temp %s→%s (%s), humidity %s→%s (%s)",
                zone_id, cloud_temp, merged_temp, temp_src,
                cloud_humidity, merged_hum, hum_src,
            )
        result = dict(zone_data)
        result["sensorDataPoints"] = sensor_data
    except (TypeError, ValueError, AttributeError):
        _LOGGER.debug("Failed to merge HomeKit data into zone %s", zone_id, exc_info=True)
        return zone_data
    else:
        return result


# Tado API only accepts: MANUAL, TADO_MODE, TIMER
_OVERLAY_API_MAP: dict[str, str] = {
    "NEXT_TIME_BLOCK": "TADO_MODE",
}


def _map_overlay_to_api(mode: str) -> str:
    """Map internal overlay mode to Tado API-accepted value."""
    return _OVERLAY_API_MAP.get(mode, mode)


def retry_delay(attempt: int, base_delay: float = RETRY_BASE_DELAY) -> float:
    """Calculate jittered retry delay for the given attempt number.

    Uses full jitter pattern: uniform random between 0 and base_delay^attempt.
    """
    return random.uniform(0, min(MAX_RETRY_DELAY, base_delay**attempt))


async def async_retry_with_backoff[T](
    callback: Callable[..., Awaitable[T]],
    *,
    max_attempts: int = MAX_RETRY_ATTEMPTS,
    no_retry_exceptions: tuple[type[Exception], ...] = (),
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
) -> T:
    """Execute callback with exponential backoff retry.

    Args:
        callback: Async callable to execute.
        max_attempts: Maximum number of attempts.
        no_retry_exceptions: Exception types that should never be retried.
        retryable_exceptions: Exception types eligible for retry.
        on_retry: Optional async callback(attempt, error) called before each retry sleep.

    Returns:
        Result of successful callback execution.

    Raises:
        The last exception if all attempts exhausted, or any no_retry_exception immediately.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await callback()
        except no_retry_exceptions:
            raise
        except retryable_exceptions as err:
            last_error = err
            if attempt >= max_attempts:
                raise
            if on_retry:
                await on_retry(attempt, err)
            delay = retry_delay(attempt)
            await asyncio.sleep(delay)
    raise last_error  # type: ignore[misc]


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> TadoDataUpdateCoordinator:
    """Get coordinator from entry_id, or None."""
    try:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and hasattr(entry, "runtime_data") and entry.runtime_data is not None:
            return entry.runtime_data  # type: ignore[no-any-return]
    except (AttributeError, TypeError):
        pass
    return None  # type: ignore[return-value]


def parse_iso_datetime(iso_str: str) -> datetime:
    """Parse an ISO 8601 datetime string to a timezone-aware UTC datetime.

    Python 3.11+ ``fromisoformat`` handles 'Z' suffix natively.
    Naive datetimes (no tzinfo) are assumed UTC.

    Args:
        iso_str: ISO 8601 datetime string.

    Returns:
        Timezone-aware datetime in UTC.

    Raises:
        ValueError: If the string cannot be parsed as ISO 8601.

    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


async def async_trigger_immediate_refresh(
    hass: HomeAssistant,
    entity_id: str,
    reason: str,
    force: bool = False,
    skip_debounce: bool = False,
) -> None:
    """Trigger immediate refresh after state change.

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID that triggered the refresh
        reason: Reason for the refresh (for logging)
        force: If True, force refresh even if recently refreshed (for buttons)
        skip_debounce: If True, skip debounce delay (for buttons)

    """
    try:
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(hass)
        entity_entry = entity_registry.async_get(entity_id)
        if entity_entry and entity_entry.config_entry_id:
            coordinator = _get_coordinator(hass, entity_entry.config_entry_id)
            if coordinator and coordinator.refresh_handler:
                await coordinator.refresh_handler.trigger_refresh(
                    entity_id,
                    reason,
                    force=force,
                    skip_debounce=skip_debounce,
                )
                return
        _LOGGER.warning("No refresh handler found for entity %s", entity_id)
    except (KeyError, TypeError, ValueError) as e:
        _LOGGER.warning("Failed to trigger immediate refresh: %s", e)


def get_optimistic_window(hass: HomeAssistant, entry_id: str | None = None) -> float:
    """Get the optimistic update window duration in seconds.

    The optimistic window = debounce_seconds + OPTIMISTIC_WINDOW_BUFFER_SECONDS.
    During this window, entities ignore API updates to preserve optimistic state.

    Args:
        hass: Home Assistant instance
        entry_id: Optional config entry ID for per-entry config lookup

    Returns:
        Optimistic window duration in seconds (default: 17.0 = 15 + 2)

    """
    from .const import DEFAULT_OPTIMISTIC_WINDOW_SECONDS, OPTIMISTIC_WINDOW_BUFFER_SECONDS

    try:
        if entry_id:
            coordinator = _get_coordinator(hass, entry_id)
            if coordinator and coordinator.config_manager:
                return float(coordinator.config_manager.get_refresh_debounce_seconds()) + OPTIMISTIC_WINDOW_BUFFER_SECONDS
    except (AttributeError, TypeError, ValueError) as err:
        _LOGGER.debug("Failed to get optimistic window from config: %s", err)
    return DEFAULT_OPTIMISTIC_WINDOW_SECONDS


def get_overlay_termination(hass: HomeAssistant, entry_id: str | None = None) -> dict[str, Any]:
    """Get the termination dict for overlay API calls.

    Args:
        hass: Home Assistant instance
        entry_id: Optional config entry ID for per-entry lookup

    Returns:
        {"type": "TADO_MODE"} or {"type": "MANUAL"} or {"type": "TIMER", "durationInSeconds": ...}
        Note: Tado API only accepts MANUAL, TADO_MODE, TIMER (not NEXT_TIME_BLOCK)

    """
    mode = OVERLAY_MODE_DEFAULT
    duration = TIMER_DURATION_DEFAULT
    if entry_id:
        try:
            coordinator = _get_coordinator(hass, entry_id)
            if coordinator:
                mode = coordinator.overlay_mode or OVERLAY_MODE_DEFAULT
                duration = coordinator.timer_duration or TIMER_DURATION_DEFAULT
        except (AttributeError, TypeError):
            pass

    # Map internal storage values to API-accepted values
    mode = _map_overlay_to_api(mode)

    if mode == "TIMER":
        return {"type": "TIMER", "durationInSeconds": duration * 60}

    return {"type": mode}


def get_zone_overlay_termination(hass: HomeAssistant, zone_id: str, entry_id: str | None = None) -> dict[str, Any]:
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
            api_mode = _map_overlay_to_api(zone_mode)

            # Handle Timer mode with duration
            if api_mode == "TIMER":
                duration = zone_config_manager.get_zone_value(zone_id, "timer_duration", TIMER_DURATION_DEFAULT)
                return {"type": "TIMER", "durationInSeconds": duration * 60}

            return {"type": api_mode}

    # Fallback to global overlay mode (handles TADO_MODE and when no per-zone config)
    return get_overlay_termination(hass, entry_id=entry_id)


def build_timer_termination(
    duration_minutes: int | None = None,
    overlay: str | None = None,
    hass: HomeAssistant | None = None,
    zone_id: str | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:
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
        api_mode = _map_overlay_to_api(overlay_upper)
        if api_mode in ("TADO_MODE", "MANUAL"):
            return {"type": api_mode}

    # Fall back to per-zone / global overlay config
    if hass and zone_id:
        return get_zone_overlay_termination(hass, zone_id, entry_id=entry_id)
    if hass:
        return get_overlay_termination(hass, entry_id=entry_id)

    # Ultimate fallback
    return {"type": "MANUAL"}
