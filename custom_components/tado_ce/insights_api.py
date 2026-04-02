"""API insights — status, quota planning, usage spike, call rate.

Provides insight functions for API-related conditions.
"""

from __future__ import annotations

from typing import Any

from .helpers import parse_iso_datetime as _parse_iso_dt
from .insights_models import (
    API_QUOTA_BUFFER_HOURS,
    API_QUOTA_HIGH_BUFFER_HOURS,
    API_USAGE_CRITICAL,
    API_USAGE_HIGH,
    API_USAGE_NOTICE,
    API_USAGE_SPIKE_RATIO,
    API_USAGE_WARNING,
    CALLS_PER_HOUR_MIN_SAMPLES,
    Insight,
    InsightPriority,
)


def calculate_api_status_recommendation(  # noqa: C901, PLR0911
    remaining_calls: int | None,
    total_calls: int | None,
    reset_time_human: str | None = None,
    current_interval_minutes: int | None = None,
) -> str:
    """Calculate SMART recommendation for API status.

    Args:
        remaining_calls: Remaining API calls
        total_calls: Total API calls allowed
        reset_time_human: Human-readable reset time (e.g., "3h 20m")
        current_interval_minutes: Current polling interval in minutes

    Returns:
        SMART recommendation string (empty if API usage is healthy)
    """
    if remaining_calls is None or total_calls is None:
        return ""

    usage_percent = ((total_calls - remaining_calls) / total_calls) * 100

    if usage_percent < API_USAGE_NOTICE:
        return ""

    # Calculate suggested interval based on remaining calls and time
    suggested_interval = None
    if current_interval_minutes:
        if usage_percent >= API_USAGE_HIGH:
            suggested_interval = max(current_interval_minutes * 2, 60)
        elif usage_percent >= API_USAGE_WARNING:
            suggested_interval = max(current_interval_minutes + 15, 30)

    reset_info = f" (resets in {reset_time_human})" if reset_time_human else ""

    if usage_percent >= API_USAGE_CRITICAL:
        return f"API CRITICAL: Only {remaining_calls} calls remaining{reset_info} \u2014 pause automations until reset"

    if usage_percent >= API_USAGE_HIGH:
        if suggested_interval:
            return (
                f"API WARNING: {remaining_calls} calls remaining{reset_info}"
                f" \u2014 increase polling to {suggested_interval} min"
                " in Settings \u2192 Tado CE \u2192 Configure"
            )
        return f"API WARNING: {remaining_calls} calls remaining{reset_info} \u2014 reduce polling frequency"

    if usage_percent >= API_USAGE_WARNING:
        if suggested_interval:
            return (
                f"API usage at {usage_percent:.0f}%{reset_info}"
                f" \u2014 consider increasing polling to {suggested_interval} min"
            )
        return f"API usage at {usage_percent:.0f}%{reset_info} \u2014 monitor usage"

    if usage_percent >= API_USAGE_NOTICE:
        return f"API usage at {usage_percent:.0f}%{reset_info}"

    return ""


def calculate_api_quota_planning_insight(
    remaining_calls: int | None = None,
    total_calls: int | None = None,  # noqa: ARG001 — used in caller context
    calls_per_hour: float | None = None,
    hours_until_reset: float | None = None,
    current_interval_minutes: float | None = None,  # noqa: ARG001 — reserved for future use
) -> Insight | None:
    """Calculate API quota planning insight.

    Triggers when projected exhaustion is < 6 hours before reset,
    suggesting polling interval adjustment.

    Args:
        remaining_calls: Remaining API calls
        total_calls: Total daily API call limit
        calls_per_hour: Current average calls per hour
        hours_until_reset: Hours until quota resets
        current_interval_minutes: Current polling interval in minutes

    Returns:
        Insight if quota exhaustion projected, None otherwise
    """
    if remaining_calls is None or calls_per_hour is None or hours_until_reset is None:
        return None
    if calls_per_hour <= 0:
        return None

    hours_remaining = remaining_calls / calls_per_hour
    buffer_hours = hours_until_reset - hours_remaining

    # Only trigger if projected to run out > 6 hours before reset
    if buffer_hours < API_QUOTA_BUFFER_HOURS:
        return None

    # Suggest new interval
    if hours_until_reset > 0 and remaining_calls > 0:
        safe_calls_per_hour = remaining_calls / hours_until_reset * 0.8  # 20% safety margin
        suggested_interval = max(60 / safe_calls_per_hour, 5) if safe_calls_per_hour > 0 else 30
    else:
        suggested_interval = 30

    rec = (
        f"API quota: {remaining_calls} calls left, "
        f"projected to run out {buffer_hours:.0f}h before reset. "
        f"Consider increasing polling interval to {suggested_interval:.0f} min"
    )

    priority = InsightPriority.HIGH if buffer_hours > API_QUOTA_HIGH_BUFFER_HOURS else InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="api_quota_planning",
        zone_name=None,
    )


def calculate_api_usage_spike_insight(
    current_hour_calls: int | None = None,
    avg_calls_per_hour: float | None = None,
) -> Insight | None:
    """Detect abnormal API usage spikes.

    Triggers when current hour's calls significantly exceed the average.

    Args:
        current_hour_calls: Number of API calls in the current hour
        avg_calls_per_hour: Average calls per hour from history

    Returns:
        Insight if usage spike detected, None otherwise
    """
    if current_hour_calls is None or avg_calls_per_hour is None:
        return None
    if avg_calls_per_hour <= 0:
        return None

    ratio = current_hour_calls / avg_calls_per_hour
    if ratio < API_USAGE_SPIKE_RATIO:
        return None

    rec = (
        f"API usage spike: {current_hour_calls} calls this hour "
        f"({ratio:.1f}x the average of {avg_calls_per_hour:.0f}/h) "
        f"\u2014 check for automation loops or integration conflicts"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="api_usage_spike",
        zone_name=None,
    )


def calculate_calls_per_hour(history: list[Any]) -> float | None:
    """Calculate average API calls per hour from call history.

    Args:
        history: List of call history dicts with "timestamp" key (ISO format)

    Returns:
        Calls per hour as float, or None if insufficient data
    """
    if not history or len(history) < CALLS_PER_HOUR_MIN_SAMPLES:
        return None
    try:
        first_ts = history[0].get("timestamp", "")
        last_ts = history[-1].get("timestamp", "")
        first_dt = _parse_iso_dt(first_ts)
        last_dt = _parse_iso_dt(last_ts)
        hours_span = (last_dt - first_dt).total_seconds() / 3600
        if hours_span <= 0:
            return None
        return len(history) / hours_span
    except (ValueError, TypeError, AttributeError):
        return None
