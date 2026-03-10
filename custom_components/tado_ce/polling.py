"""Tado CE adaptive polling interval management — burst mode, cooldown, quota-aware."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from .config_manager import ConfigurationManager

_LOGGER = logging.getLogger(__name__)

# Debug logging threshold — log when quota drops below this
_VERY_LOW_QUOTA_REMAINING = 10


def _get_calls_per_sync(config_manager: ConfigurationManager) -> int:
    """Calculate API calls per sync based on enabled features.

    Helper for adaptive polling calculation.

    Args:
        config_manager: Configuration manager with feature settings

    Returns:
        Number of API calls per sync cycle
    """
    calls = 1  # Base: zoneStates API call

    if config_manager.get_weather_enabled():
        calls += 1  # weather API call

    if config_manager.get_mobile_devices_enabled() and config_manager.get_mobile_devices_frequent_sync():
        calls += 1  # mobileDevices API call

    return calls


def _calculate_adaptive_interval(ratelimit_data: dict[str, Any], config_manager: ConfigurationManager) -> int:
    """Calculate adaptive polling interval based on remaining quota, Day/Night period, and Reset Time.

    Pure adaptive polling - distributes remaining calls over remaining time.
    Works universally for ANY quota tier (100, 5000, 20000, etc.)

    Simplified - reads directly from ratelimit_data which already contains
    simulated values when Test Mode is ON.

    Day/Night aware adaptive polling:
    - Night period: Fixed MAX_POLLING_INTERVAL (120 min) to conserve quota
    - Day period: Adaptive based on remaining quota after reserving Night calls
    - Respects existing quota protection (SAFETY_BUFFER, RESERVE_CALLS)
    - Considers Reset Time: if reset is soon, use quota more aggressively

    Args:
        ratelimit_data: Rate limit data with 'remaining', 'reset_seconds', 'last_reset_utc'
                        (already simulated when Test Mode is ON)
        config_manager: Configuration manager for feature settings

    Returns:
        Polling interval in minutes (constrained by MIN/MAX)
    """
    from homeassistant.util import dt as dt_util

    remaining = ratelimit_data.get("remaining", 100)
    test_mode = ratelimit_data.get("test_mode", False)

    # Get reset time info
    reset_seconds = ratelimit_data.get("reset_seconds", 86400)
    last_reset_utc = ratelimit_data.get("last_reset_utc")

    # Only recalculate reset_seconds from last_reset_utc in LIVE mode
    # In Test Mode, reset_seconds is already correctly calculated from test_mode_start_time
    # Recalculating from last_reset_utc (which is Live mode's reset) causes wrong intervals
    # Test Mode polling stuck if this is not handled
    if not test_mode and last_reset_utc:
        try:
            last_reset = datetime.fromisoformat(last_reset_utc)
            if last_reset.tzinfo is None:
                last_reset = last_reset.replace(tzinfo=UTC)

            next_reset = last_reset + timedelta(hours=24)
            now_utc = datetime.now(UTC)

            # If next_reset is in the past, add 24h until it's in the future
            while next_reset <= now_utc:
                next_reset += timedelta(hours=24)

            calculated_reset_seconds = int((next_reset - now_utc).total_seconds())
            if calculated_reset_seconds > 0:
                reset_seconds = calculated_reset_seconds
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Failed to calculate dynamic reset_seconds: %s", e)

    reset_hours = reset_seconds / 3600

    if test_mode:
        _LOGGER.debug("Tado CE: Test Mode - using simulated remaining=%s from ratelimit.json", remaining)

    # Account for optional features (weather, mobile devices)
    calls_per_sync = _get_calls_per_sync(config_manager)
    effective_remaining = remaining / calls_per_sync

    # Safety check: if no remaining quota, use max interval
    if effective_remaining <= 0:
        _LOGGER.debug(
            "Tado CE: No remaining quota (effective_remaining=%s). Using max interval: %s min",
            effective_remaining,
            MAX_POLLING_INTERVAL,
        )
        return MAX_POLLING_INTERVAL

    # Day/Night aware adaptive polling with Reset Time consideration
    now = dt_util.now()
    current_hour = now.hour
    day_start = config_manager.get_day_start_hour()
    night_start = config_manager.get_night_start_hour()

    # Check if currently in Day or Night period
    is_day = is_daytime(config_manager)

    # Calculate usable quota after safety buffer and reserve
    usable_quota = effective_remaining * POLLING_SAFETY_BUFFER - QUOTA_RESERVE_CALLS

    # Handle Uniform Mode (day_start == night_start)
    # In Uniform Mode, there's no Day/Night distinction, so use full reset_hours
    # and don't reserve any quota for Night period
    if day_start == night_start:
        # Uniform Mode - no Day/Night distinction
        effective_hours = reset_hours
        night_calls_needed = 0
        time_boundary = f"Reset ({reset_hours:.1f}h)"

        day_quota = max(0, usable_quota - night_calls_needed)

        if day_quota <= 0 or effective_hours <= 0:
            _LOGGER.debug(
                "Tado CE: No quota available (day_quota=%.1f, effective_hours=%.1f). Using max interval.",
                day_quota,
                effective_hours,
            )
            return MAX_POLLING_INTERVAL

        # Calculate interval for Uniform Mode
        effective_minutes = effective_hours * 60
        interval_minutes = effective_minutes / day_quota

        # Apply constraints (min 5, max 120)
        interval_minutes = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, interval_minutes)))

        _LOGGER.debug(
            "Tado CE Adaptive Polling (Uniform Mode):\n"
            "  Period: Uniform (Day Start = Night Start = %s)\n"
            "  Effective hours: %.1fh (until %s)\n"
            "  Remaining: %s calls (effective: %.0f)\n"
            "  Usable quota: %.0f\n"
            "  Calculated: %.1f min → Adaptive: %s min\n"
            "  Reset in: %.1fh | Test Mode: %s",
            day_start,
            effective_hours,
            time_boundary,
            remaining,
            effective_remaining,
            usable_quota,
            effective_minutes / day_quota,
            interval_minutes,
            reset_hours,
            test_mode,
        )

        return interval_minutes

    # Smart Day/Night for Low Quota
    # For low-quota users (remaining <= 100), use a different strategy:
    # - Night: Fixed MAX_POLLING_INTERVAL (120 min) to conserve quota
    # - Day: Use remaining quota after reserving Night calls
    # This ensures 24h coverage regardless of when reset occurs
    if remaining <= LOW_QUOTA_THRESHOLD:
        # Calculate Night duration
        if night_start > day_start:
            night_duration = 24 - night_start + day_start
        else:
            night_duration = day_start - night_start

        # Calculate Day duration
        day_duration = 24 - night_duration

        # Night calls at MAX_POLLING_INTERVAL (120 min)
        night_calls = (night_duration * 60) / MAX_POLLING_INTERVAL

        # Apply safety buffer and quota reserve to effective_remaining
        # This preserves the existing quota protection behavior (Requirement 3.5)
        usable_remaining = effective_remaining * POLLING_SAFETY_BUFFER - QUOTA_RESERVE_CALLS

        # Day calls = usable_remaining - night_calls
        day_calls = usable_remaining - night_calls

        # Edge case: if usable_remaining <= night_calls, use MAX_POLLING_INTERVAL for both
        if day_calls <= 0:
            _LOGGER.debug(
                "Tado CE Adaptive Polling (Low Quota - Edge Case):\n"
                "  Remaining: %s calls (usable: %.1f) <= Night calls needed (%.1f)\n"
                "  Using MAX_POLLING_INTERVAL (%s min) for all periods\n"
                "  Test Mode: %s",
                remaining,
                usable_remaining,
                night_calls,
                MAX_POLLING_INTERVAL,
                test_mode,
            )
            if not is_day:
                return None  # type: ignore[return-value]  # Night period - use default/custom night interval
            return MAX_POLLING_INTERVAL

        # Calculate Day interval
        day_interval = (day_duration * 60) / day_calls

        if not is_day:
            # Night period - return None to use default/custom night interval
            _LOGGER.debug(
                "Tado CE Adaptive Polling (Low Quota - Night):\n"
                "  Period: Night (until %02d:00)\n"
                "  Remaining: %s calls (effective: %.0f, usable: %.1f)\n"
                "  Night calls reserved: %.1f at %s min\n"
                "  Day calls available: %.1f at %.1f min\n"
                "  Returning None (use default/custom night interval)\n"
                "  Test Mode: %s",
                day_start,
                remaining,
                effective_remaining,
                usable_remaining,
                night_calls,
                MAX_POLLING_INTERVAL,
                day_calls,
                day_interval,
                test_mode,
            )
            return None  # type: ignore[return-value]

        # Day period - use calculated day_interval
        day_interval = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, day_interval)))

        _LOGGER.debug(
            "Tado CE Adaptive Polling (Low Quota - Day):\n"
            "  Period: Day (Smart Day/Night for Low Quota)\n"
            "  Remaining: %s calls (effective: %.0f)\n"
            "  Night duration: %sh → %.1f calls at %s min\n"
            "  Day duration: %sh → %.1f calls at %s min\n"
            "  Reset in: %.1fh | Test Mode: %s",
            remaining,
            effective_remaining,
            night_duration,
            night_calls,
            MAX_POLLING_INTERVAL,
            day_duration,
            day_calls,
            day_interval,
            reset_hours,
            test_mode,
        )

        return day_interval

    # Normal Day/Night Mode calculation
    # Calculate hours until Night Start (for Day period)
    if is_day:
        if current_hour < night_start:
            hours_until_night = night_start - current_hour
        else:
            # current_hour >= night_start means we're past night_start today
            # This shouldn't happen if is_day is True, but handle edge case
            hours_until_night = 24 - current_hour + night_start
    else:
        hours_until_night = 0

    # Calculate Night duration (for quota reservation)
    if night_start > day_start:
        night_duration = 24 - night_start + day_start
    else:
        night_duration = day_start - night_start

    # Key insight - if Reset Time is before Night Start, we don't need to reserve Night quota!
    # Because quota will reset and we'll have fresh quota for Night.

    # Night period returns None to signal "use default/custom night interval"
    if not is_day:
        _LOGGER.debug(
            "Tado CE Adaptive Polling (Night):\n"
            "  Period: Night (until %02d:00)\n"
            "  Reset in: %.1fh\n"
            "  Remaining: %s calls\n"
            "  Returning None (use default/custom night interval)\n"
            "  Test Mode: %s",
            day_start,
            reset_hours,
            remaining,
            test_mode,
        )
        return None  # type: ignore[return-value]  # Signal to use default/custom night interval

    # Day period: calculate adaptive interval
    # Determine effective time window (until Reset or Night Start, whichever is sooner)
    if reset_hours < hours_until_night:
        # Reset is before Night Start - use all quota until reset, no need to reserve for Night
        effective_hours = reset_hours
        night_calls_needed = 0
        time_boundary = f"Reset ({reset_hours:.1f}h)"
    else:
        # Night Start is before Reset - need to reserve quota for Night
        effective_hours = hours_until_night
        # Use custom night interval if set, otherwise MAX_POLLING_INTERVAL
        custom_night = config_manager.get_custom_night_interval()
        night_interval_for_calc = custom_night if custom_night is not None else MAX_POLLING_INTERVAL
        night_calls_needed = (night_duration * 60) / night_interval_for_calc  # type: ignore[assignment]
        time_boundary = f"Night Start ({hours_until_night}h)"

    day_quota = max(0, usable_quota - night_calls_needed)

    if day_quota <= 0 or effective_hours <= 0:
        _LOGGER.debug(
            "Tado CE: No Day quota available (day_quota=%.1f, effective_hours=%.1f). Using max interval.",
            day_quota,
            effective_hours,
        )
        return MAX_POLLING_INTERVAL

    # Calculate Day interval
    effective_minutes = effective_hours * 60
    interval_minutes = effective_minutes / day_quota

    # Apply constraints (min 5, max 120)
    interval_minutes = int(max(MIN_POLLING_INTERVAL, min(MAX_POLLING_INTERVAL, interval_minutes)))

    # Log adaptive calculation
    _LOGGER.debug(
        "Tado CE Adaptive Polling (Day):\n"
        "  Period: Day (until %s)\n"
        "  Effective hours: %.1fh\n"
        "  Night reserved: %.1f calls\n"
        "  Remaining: %s calls (effective: %.0f)\n"
        "  Usable quota: %.0f → Day quota: %.0f\n"
        "  Calculated: %.1f min → Adaptive: %s min\n"
        "  Reset in: %.1fh | Test Mode: %s",
        time_boundary,
        effective_hours,
        night_calls_needed,
        remaining,
        effective_remaining,
        usable_quota,
        day_quota,
        effective_minutes / day_quota,
        interval_minutes,
        reset_hours,
        test_mode,
    )

    # Log at DEBUG level if quota is very low
    if remaining < _VERY_LOW_QUOTA_REMAINING:
        _LOGGER.debug("Tado CE: Low quota (%s remaining). Using interval: %s min", remaining, interval_minutes)

    return interval_minutes


def should_pause_polling(ratelimit_data: dict[str, Any], config_manager: ConfigurationManager) -> tuple[bool, str]:
    """Check if polling should be paused to reserve quota for manual operations.

    Pauses polling when quota is critically low to ensure users can still
    perform manual operations (set temperature, etc.). If reset time has
    passed, resumes polling to detect the actual reset from API headers.

    Args:
        ratelimit_data: Rate limit data with 'remaining', 'used', 'reset_seconds'
                        (already simulated when Test Mode is ON)
        config_manager: Configuration manager for feature settings

    Returns:
        Tuple of (should_pause: bool, reason: str)
            - should_pause: True if polling should be paused
            - reason: Human-readable explanation (empty if not pausing)
    """
    # Check if Quota Reserve Protection is enabled
    if not config_manager.get_quota_reserve_enabled():
        _LOGGER.debug("Tado CE: Quota Reserve Protection disabled, not pausing polling")
        return False, ""

    test_mode = ratelimit_data.get("test_mode", False)
    _LOGGER.debug(
        "Tado CE: should_pause_polling called with used=%s, remaining=%s, test_mode=%s",
        ratelimit_data.get("used"),
        ratelimit_data.get("remaining"),
        test_mode,
    )

    # Check if reset time has passed - if so, resume polling to detect reset
    last_reset_utc = ratelimit_data.get("last_reset_utc")
    if last_reset_utc:
        try:
            last_reset = datetime.fromisoformat(last_reset_utc)
            next_reset = last_reset + timedelta(hours=24)
            now_utc = datetime.now(UTC)

            # If next reset time has passed, resume polling to detect actual reset
            if now_utc >= next_reset:
                _LOGGER.info(
                    "Tado CE: Reset time has passed (expected %s UTC). Resuming polling to detect actual reset.",
                    next_reset.strftime("%H:%M"),
                )
                return False, ""
        except (ValueError, TypeError) as e:
            _LOGGER.debug("Failed to check reset time: %s", e)

    # No need to recalculate - save_ratelimit() stores the correct values
    remaining = ratelimit_data.get("remaining", 100)
    daily_limit = ratelimit_data.get("limit", 100)

    # Calculate reserve threshold: max of absolute minimum or percentage
    reserve_threshold = max(QUOTA_RESERVE_CALLS, int(daily_limit * QUOTA_RESERVE_PERCENT))

    _LOGGER.debug(
        "Tado CE: should_pause_polling check - remaining=%s, limit=%s, threshold=%s, should_pause=%s",
        remaining,
        daily_limit,
        reserve_threshold,
        remaining <= reserve_threshold,
    )

    # Check if we should pause
    if remaining <= reserve_threshold:
        reset_seconds = ratelimit_data.get("reset_seconds", 0)
        hours = reset_seconds // 3600
        minutes = (reset_seconds % 3600) // 60

        reason = (
            f"Quota critically low ({remaining} remaining, reserve threshold={reserve_threshold}). "
            f"Polling paused until reset in {hours}h {minutes}m. "
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
    from homeassistant.util import dt as dt_util

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


def get_polling_interval(config_manager: ConfigurationManager, cached_ratelimit: dict[str, Any] | None = None) -> int:
    """Get polling interval based on configuration and API rate limit.

    Uses adaptive polling based on remaining quota and time until reset.
    Custom intervals are treated as targets, but adaptive polling can
    override if quota is low. Day/Night aware — custom intervals are
    only used as override when explicitly set by user.

    Args:
        config_manager: Configuration manager with polling settings
        cached_ratelimit: Pre-loaded ratelimit data (to avoid blocking I/O in async context)

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
            adaptive_interval = _calculate_adaptive_interval(ratelimit_data, config_manager)

    except (ValueError, TypeError, AttributeError) as e:
        _LOGGER.debug("Could not calculate adaptive polling interval, using default: %s", e)

    # Decision logic - respect user custom override for high-quota users
    # Custom intervals below 5 min were being ignored because adaptive
    # interval is clamped to MIN_POLLING_INTERVAL (5 min) by default.
    # Fix: When user explicitly sets custom interval, use it directly unless
    # quota is actually insufficient (not just because of MIN_POLLING_INTERVAL clamp).
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
        _LOGGER.info(
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


def _log_quota_warning_if_needed(interval: int, daytime: bool, config_manager: ConfigurationManager) -> None:
    """Log warning if custom interval would exceed API quota.

    Args:
        interval: Custom polling interval in minutes
        daytime: Whether it's currently daytime
        config_manager: Configuration manager
    """
    # Assuming 2-3 API calls per sync (zoneStates + weather if enabled)
    weather_enabled = config_manager.get_weather_enabled()
    calls_per_sync = 2 if weather_enabled else 1

    # Get both intervals to calculate total daily calls
    day_interval = config_manager.get_custom_day_interval() or DEFAULT_DAY_INTERVAL
    night_interval = config_manager.get_custom_night_interval() or DEFAULT_NIGHT_INTERVAL

    # Assume 16 hours day, 8 hours night (based on default 7am-11pm)
    day_hours = 16
    night_hours = 8

    day_syncs = (day_hours * 60) / day_interval
    night_syncs = (night_hours * 60) / night_interval
    total_calls = (day_syncs + night_syncs) * calls_per_sync

    # Warn if exceeding low-tier quota (100 calls/day)
    low_tier_quota = 100
    if total_calls > low_tier_quota:
        _LOGGER.warning(
            "Tado CE: Custom polling intervals may exceed API quota for 100-call tier. "
            "Estimated %.0f calls/day with day=%sm, night=%sm. "
            "Consider increasing intervals or check if you have a higher quota tier (5000/20000).",
            total_calls,
            day_interval,
            night_interval,
        )
