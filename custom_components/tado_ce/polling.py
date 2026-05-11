"""Tado CE adaptive polling interval management — day/night, quota-aware, low-quota protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_DAY_INTERVAL,
    DEFAULT_NIGHT_INTERVAL,
    LOW_QUOTA_THRESHOLD,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    POLLING_SAFETY_BUFFER,
    QUOTA_RESERVE_CALLS,
    QUOTA_RESERVE_PERCENT,
)
from .helpers import parse_iso_datetime

if TYPE_CHECKING:
    from .config_manager import ConfigurationManager

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PollingContext:
    """Derived polling calculation context — all values needed by mode helpers."""

    remaining: int
    effective_remaining: float
    usable_quota: float
    reset_hours: float
    is_day: bool
    is_uniform_mode: bool
    day_start: int
    night_start: int
    current_hour: int
    calls_per_sync: int
    night_duration: int
    day_duration: int


def _get_calls_per_sync(
    config_manager: ConfigurationManager,
    homekit_connected: bool = False,
) -> int:
    """Calculate API calls per sync based on enabled features.

    Helper for adaptive polling calculation.

    Args:
        config_manager: Configuration manager with feature settings
        homekit_connected: If True, skip zoneStates base call (local data available)

    Returns:
        Number of API calls per sync cycle
    """
    # Base: zoneStates API call (skip if HomeKit provides temperature/humidity)
    calls = 0 if homekit_connected else 1

    if config_manager.get_weather_enabled():
        calls += 1  # weather API call

    if config_manager.get_mobile_devices_enabled() and config_manager.get_mobile_devices_frequent_sync():
        calls += 1  # mobileDevices API call

    if config_manager.get_home_state_sync_enabled():
        calls += 1  # home state API call

    return calls


def _build_polling_context(
    ratelimit_data: dict[str, Any],
    config_manager: ConfigurationManager,
    homekit_connected: bool = False,
) -> _PollingContext:
    """Compute all derived polling values from ratelimit data and config.

    Centralises reset-time recalculation, calls-per-sync adjustment,
    day/night detection, and quota budgeting into a single immutable context
    consumed by the mode-specific helpers.
    """
    _remaining = ratelimit_data.get("remaining")
    remaining: int = int(_remaining) if _remaining is not None else 100
    _reset_sec = ratelimit_data.get("reset_seconds")
    reset_seconds: int = int(_reset_sec) if _reset_sec is not None else 86400
    last_reset_utc = ratelimit_data.get("last_reset_utc")

    # Recalculate reset_seconds from last_reset_utc
    if last_reset_utc:
        from .ratelimit import calculate_seconds_until_reset

        calculated = calculate_seconds_until_reset(last_reset_utc)
        if calculated is not None:
            reset_seconds = calculated

    reset_hours = reset_seconds / 3600

    calls_per_sync = max(1, _get_calls_per_sync(config_manager, homekit_connected=homekit_connected))
    effective_remaining = remaining / calls_per_sync
    usable_quota = effective_remaining * POLLING_SAFETY_BUFFER - QUOTA_RESERVE_CALLS

    now = dt_util.now()
    day_start = config_manager.get_day_start_hour()
    night_start = config_manager.get_night_start_hour()
    is_day = is_daytime(config_manager)

    # Night / Day durations
    if night_start > day_start:
        night_duration = 24 - night_start + day_start
    else:
        night_duration = day_start - night_start
    day_duration = 24 - night_duration

    return _PollingContext(
        remaining=remaining,
        effective_remaining=effective_remaining,
        usable_quota=usable_quota,
        reset_hours=reset_hours,
        is_day=is_day,
        is_uniform_mode=(day_start == night_start),
        day_start=day_start,
        night_start=night_start,
        current_hour=now.hour,
        calls_per_sync=calls_per_sync,
        night_duration=night_duration,
        day_duration=day_duration,
    )


def _calculate_uniform_interval(ctx: _PollingContext) -> int:
    """Calculate polling interval for Uniform Mode (day_start == night_start).

    No Day/Night distinction — distributes quota evenly over the full reset window.
    """
    effective_hours = ctx.reset_hours
    night_calls_needed = 0

    day_quota = max(0, ctx.usable_quota - night_calls_needed)

    if day_quota <= 0 or effective_hours <= 0:
        return MAX_POLLING_INTERVAL

    effective_minutes = effective_hours * 60
    interval_minutes = effective_minutes / day_quota
    interval_minutes = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, interval_minutes)))

    _LOGGER.debug(
        "Adaptive polling (uniform): %dmin (remaining=%s, usable=%.0f, reset=%.1fh)",
        interval_minutes, ctx.remaining, ctx.usable_quota, ctx.reset_hours,
    )

    return interval_minutes


def _calculate_low_quota_interval(ctx: _PollingContext) -> int | None:
    """Calculate polling interval for low-quota users (remaining <= LOW_QUOTA_THRESHOLD).

    Night: Fixed MAX_POLLING_INTERVAL to conserve quota.
    Day: Distributes remaining quota after reserving Night calls.
    """
    night_calls = (ctx.night_duration * 60) / MAX_POLLING_INTERVAL
    usable_remaining = ctx.effective_remaining * POLLING_SAFETY_BUFFER - QUOTA_RESERVE_CALLS
    day_calls = usable_remaining - night_calls

    # Edge case: not enough quota for both day and night
    if day_calls <= 0:
        if not ctx.is_day:
            return None  # Night period — use default/custom night interval
        return MAX_POLLING_INTERVAL

    if not ctx.is_day:
        return None  # Night period — use default/custom night interval

    day_interval = (ctx.day_duration * 60) / day_calls
    day_interval = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, day_interval)))

    _LOGGER.debug(
        "Adaptive polling (low quota, day): %dmin (remaining=%s, day_calls=%.0f, night_reserved=%.0f)",
        day_interval, ctx.remaining, day_calls, night_calls,
    )

    return day_interval


def _calculate_day_night_interval(
    ctx: _PollingContext,
    config_manager: ConfigurationManager,
) -> int | None:
    """Calculate polling interval for normal Day/Night mode with reset-time awareness.

    Night: Returns None to signal use of default/custom night interval.
    Day: Adaptive based on remaining quota, considering whether reset occurs
    before or after Night Start.
    """
    # Night period — signal to use default/custom night interval
    if not ctx.is_day:
        return None

    # Day period — calculate hours until night
    if ctx.current_hour < ctx.night_start:
        hours_until_night = ctx.night_start - ctx.current_hour
    else:
        hours_until_night = 24 - ctx.current_hour + ctx.night_start

    # Determine effective time window (until Reset or Night Start, whichever is sooner)
    if ctx.reset_hours < hours_until_night:
        # Reset is before Night Start — use all quota until reset, no need to reserve for Night
        effective_hours = ctx.reset_hours
        night_calls_needed = 0.0
        time_boundary = f"reset ({ctx.reset_hours:.1f}h)"
    else:
        # Night Start is before Reset — need to reserve quota for Night
        effective_hours = float(hours_until_night)
        custom_night = config_manager.get_custom_night_interval()
        night_interval_for_calc = custom_night if custom_night is not None else MAX_POLLING_INTERVAL
        night_calls_needed = (ctx.night_duration * 60) / night_interval_for_calc
        time_boundary = f"night ({hours_until_night}h)"

    day_quota = max(0, ctx.usable_quota - night_calls_needed)

    if day_quota <= 0 or effective_hours <= 0:
        return MAX_POLLING_INTERVAL

    effective_minutes = effective_hours * 60
    interval_minutes = effective_minutes / day_quota
    interval_minutes = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, interval_minutes)))

    _LOGGER.debug(
        "Adaptive polling (day, until %s): %dmin (remaining=%s, day_quota=%.0f, night_reserved=%.0f)",
        time_boundary, interval_minutes, ctx.remaining, day_quota, night_calls_needed,
    )

    return interval_minutes


def calculate_adaptive_interval(
    ratelimit_data: dict[str, Any],
    config_manager: ConfigurationManager,
    homekit_connected: bool = False,
) -> int | None:
    """Calculate adaptive polling interval — thin orchestrator.

    Delegates to mode-specific helpers based on quota level and Day/Night config.
    """
    ctx = _build_polling_context(ratelimit_data, config_manager, homekit_connected=homekit_connected)

    # No remaining quota — use max interval
    if ctx.effective_remaining <= 0:
        _LOGGER.debug(
            "Tado CE: No remaining quota (effective_remaining=%s). Using max interval: %s min",
            ctx.effective_remaining,
            MAX_POLLING_INTERVAL,
        )
        return MAX_POLLING_INTERVAL

    # Uniform Mode (day_start == night_start)
    if ctx.is_uniform_mode:
        return _calculate_uniform_interval(ctx)

    # Low-quota Smart Day/Night
    if ctx.remaining <= LOW_QUOTA_THRESHOLD:
        return _calculate_low_quota_interval(ctx)

    # Normal Day/Night with reset-time awareness
    return _calculate_day_night_interval(ctx, config_manager)
def should_pause_polling(ratelimit_data: dict[str, Any], config_manager: ConfigurationManager) -> tuple[bool, str]:
    """Check if polling should be paused to reserve quota for manual operations.

    Pauses polling when quota is critically low to ensure users can still
    perform manual operations (set temperature, etc.). If reset time has
    passed, resumes polling to detect the actual reset from API headers.

    Args:
        ratelimit_data: Rate limit data with 'remaining', 'used', 'reset_seconds'
        config_manager: Configuration manager for feature settings

    Returns:
        Tuple of (should_pause: bool, reason: str)
            - should_pause: True if polling should be paused
            - reason: Human-readable explanation (empty if not pausing)
    """
    # Check if Quota Reserve Protection is enabled
    if not config_manager.get_quota_reserve_enabled():
        return False, ""

    # Check if reset time has passed - if so, resume polling to detect reset
    last_reset_utc = ratelimit_data.get("last_reset_utc")
    if last_reset_utc:
        try:
            last_reset = parse_iso_datetime(last_reset_utc)
            next_reset = last_reset + timedelta(hours=24)
            now_utc = dt_util.utcnow()

            # If next reset time has passed, resume polling to detect actual reset
            if now_utc >= next_reset:
                _LOGGER.info(
                    "Tado CE: Reset time has passed (expected %s UTC). Resuming polling to detect actual reset.",
                    next_reset.strftime("%H:%M"),
                )
                return False, ""
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Failed to check reset time: %s", e)
    else:
        # No reset time known (fresh install / stale data) — allow polling
        # so we can bootstrap ratelimit data from API response headers.
        return False, ""

    # No need to recalculate - save_ratelimit() stores the correct values
    _remaining = ratelimit_data.get("remaining")
    remaining = _remaining if _remaining is not None else 100
    _limit = ratelimit_data.get("limit")
    daily_limit = _limit if _limit is not None else 100

    # Calculate reserve threshold: max of absolute minimum or percentage
    reserve_threshold = max(QUOTA_RESERVE_CALLS, int(daily_limit * QUOTA_RESERVE_PERCENT))

    # Check if we should pause
    if remaining <= reserve_threshold:
        # Calculate reset time: prefer reset_seconds, then last_reset_utc, then unknown
        _rs = ratelimit_data.get("reset_seconds")
        reset_seconds = _rs if _rs is not None else 0

        # If reset_seconds is 0/None, try to calculate from last_reset_utc
        if not reset_seconds and last_reset_utc:
            from .ratelimit import calculate_seconds_until_reset

            reset_seconds = calculate_seconds_until_reset(last_reset_utc) or 0

        if reset_seconds > 0:
            hours = reset_seconds // 3600
            minutes = (reset_seconds % 3600) // 60
            reset_info = f"reset in {hours}h {minutes}m"
        else:
            reset_info = "reset time unknown — will resume after first successful API response"

        reason = (
            f"Quota critically low ({remaining} remaining, reserve threshold={reserve_threshold}). "
            f"Polling paused until {reset_info}. "
            f"Manual operations (set temperature, etc.) still available."
        )
        return True, reason

    return False, ""


def is_daytime(config_manager: ConfigurationManager) -> bool:
    """Check if current time is daytime based on configured hours.

    Args:
        config_manager: Configuration manager with day/night hour settings

    Returns:
        True if current time is within day hours, False otherwise

    Note:
        If day_start == night_start, returns True (uniform mode - always day polling)
    """
    # Use HA's timezone-aware current time
    now = dt_util.now()
    hour = now.hour

    day_start = config_manager.get_day_start_hour()
    night_start = config_manager.get_night_start_hour()

    # Uniform mode: if day_start == night_start, always use day interval
    if day_start == night_start:
        return True

    # Handle wrap-around case
    # Normal case: day_start < night_start (e.g., day=6, night=22)
    if day_start < night_start:
        return day_start <= hour < night_start

    # Wrap-around case: night_start < day_start (e.g., night=1, day=6)
    # Day is from day_start to 24 OR from 0 to night_start
    return hour >= day_start or hour < night_start


def get_polling_interval(
    config_manager: ConfigurationManager,
    cached_ratelimit: dict[str, Any] | None = None,
    homekit_connected: bool = False,
) -> int:
    """Get polling interval based on configuration and API rate limit.

    Uses adaptive polling based on remaining quota and time until reset.
    Custom intervals are treated as targets, but adaptive polling can
    override if quota is low. Day/Night aware — custom intervals are
    only used as override when explicitly set by user.

    Args:
        config_manager: Configuration manager with polling settings
        cached_ratelimit: Pre-loaded ratelimit data (to avoid blocking I/O in async context)
        homekit_connected: If True, HomeKit is providing local data (fewer API calls needed)

    Returns:
        Polling interval in minutes
    """
    daytime = is_daytime(config_manager)

    # Check if user has explicitly set custom intervals
    # Only use custom interval if user explicitly configured it (not default)
    custom_day_interval = config_manager.get_custom_day_interval()
    custom_night_interval = config_manager.get_custom_night_interval()

    user_set_custom = False
    custom_interval = None
    if daytime and custom_day_interval is not None:
        custom_interval = custom_day_interval
        user_set_custom = True
    elif not daytime and custom_night_interval is not None:
        custom_interval = custom_night_interval
        user_set_custom = True

    # Calculate adaptive interval based on remaining quota
    adaptive_interval = None
    try:
        ratelimit_data = None

        if cached_ratelimit is not None:
            # Use pre-loaded data (async-safe)
            ratelimit_data = cached_ratelimit

        if ratelimit_data:
            adaptive_interval = calculate_adaptive_interval(
                ratelimit_data, config_manager, homekit_connected=homekit_connected,
            )

    except (ValueError, TypeError, AttributeError) as e:
        _LOGGER.debug("Could not calculate adaptive polling interval, using default: %s", e)

    # When the user has explicitly set a custom interval, honour it even below
    # MIN_POLLING_INTERVAL (5 min). Adaptive interval is normally clamped to
    # MIN_POLLING_INTERVAL, so without this branch, high-quota users would see
    # their custom <5min intervals silently overridden. Only override the custom
    # value when adaptive indicates the quota is *genuinely* insufficient
    # (adaptive > custom AND adaptive > MIN_POLLING_INTERVAL, i.e. not just hitting the clamp).
    if user_set_custom and custom_interval is not None:
        # User explicitly set custom interval - check if quota is actually sufficient
        if adaptive_interval is not None:
            # Calculate what the "raw" adaptive interval would be without MIN_POLLING_INTERVAL clamp
            # If adaptive > custom AND adaptive > MIN_POLLING_INTERVAL, quota is truly insufficient
            if adaptive_interval > custom_interval and adaptive_interval > MIN_POLLING_INTERVAL:
                _LOGGER.warning(
                    "Tado CE: Custom interval (%s min) would exceed quota. "
                    "Using adaptive interval (%s min) to protect remaining calls.",
                    custom_interval,
                    adaptive_interval,
                )
                return adaptive_interval
        # Custom interval is safe (or no ratelimit data), use it
        _LOGGER.debug(
            "Tado CE: Using custom %s interval: %s min",
            "day" if daytime else "night",
            custom_interval,
        )
        return custom_interval
    if adaptive_interval is not None:
        # No custom interval set - use pure adaptive (Day/Night aware)
        return adaptive_interval
    # Fallback to default intervals
    return DEFAULT_DAY_INTERVAL if daytime else DEFAULT_NIGHT_INTERVAL

