"""Actionable insights calculator for Tado CE sensors.

Provides SMART recommendation calculations for environment,
thermal analytics, device status sensors, and window predicted detection.

SMART = Specific, Measurable, Achievable, Relevant, Time-bound
"""
import math
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Optional


class InsightPriority(IntEnum):
    """Priority levels for insights (higher = more urgent)."""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Insight:
    """Represents an actionable insight."""
    priority: InsightPriority
    recommendation: str
    insight_type: str  # e.g., "mold_risk", "comfort", "battery", "window_predicted"
    zone_name: Optional[str] = None


from .models import InsightTemperatureReading  # noqa: E402

# Backward compat alias — existing code may import TemperatureReading from here
TemperatureReading = InsightTemperatureReading


@dataclass
class WindowPredictedResult:
    """Result of window predicted detection."""
    detected: bool
    confidence: str  # "none", "low", "medium", "high"
    temp_drop: float
    time_window_minutes: int
    recommendation: str
    anomaly_readings: int = 0


# ============ Window Predicted Detection ============

def detect_window_predicted(
    readings: list[TemperatureReading],
    hvac_active: bool,
    zone_name: str = "Room",
    temp_threshold: float = 1.5,
    time_window_minutes: int = 5,
    humidity_check: bool = True,
    hvac_mode: str = "heating",
    consecutive_drops: int = 2,
) -> WindowPredictedResult:
    """Detect possible open window via heating/cooling anomaly detection.

    When HVAC is active but temperature moves in the wrong direction across
    consecutive polling readings, an open window is the most likely cause.

    Args:
        readings: List of temperature readings (oldest first)
        hvac_active: Whether HVAC is currently heating/cooling
        zone_name: Name of the zone for specific recommendations
        temp_threshold: Unused, kept for backward compatibility
        time_window_minutes: Kept for backward compat in result
        humidity_check: Unused, kept for backward compatibility
        hvac_mode: "heating" or "cooling" — determines anomaly direction
        consecutive_drops: Min consecutive anomalous readings to trigger (default 2)

    Returns:
        WindowPredictedResult with detection status and SMART recommendation
    """
    _not_detected = WindowPredictedResult(
        detected=False,
        confidence="none",
        temp_drop=0.0,
        time_window_minutes=time_window_minutes,
        recommendation="",
        anomaly_readings=0,
    )

    # Detection REQUIRES active HVAC — temperature drops without heating are natural
    if not hvac_active:
        return _not_detected

    # Need at least 2 readings to compare consecutive pairs
    if len(readings) < 2:
        return _not_detected

    # Count consecutive anomalous readings from most recent backward
    # For heating: anomaly = temperature dropped (newer < older)
    # For cooling: anomaly = temperature rose (newer > older)
    anomaly_count = 0
    for i in range(len(readings) - 1, 0, -1):
        newer = readings[i].temperature
        older = readings[i - 1].temperature
        if hvac_mode == "heating":
            is_anomaly = newer < older
        else:  # cooling
            is_anomaly = newer > older
        if is_anomaly:
            anomaly_count += 1
        else:
            break  # streak broken

    if anomaly_count < consecutive_drops:
        return _not_detected

    # Calculate total temperature change across anomalous readings
    start_idx = len(readings) - 1 - anomaly_count
    total_change = abs(readings[start_idx].temperature - readings[-1].temperature)

    # Determine confidence based on count and magnitude
    if anomaly_count >= 3 and total_change >= 1.5:
        confidence = "high"
    elif anomaly_count >= 3 or total_change >= 1.0:
        confidence = "medium"
    else:
        confidence = "low"

    # Context-aware recommendation
    if hvac_mode == "heating":
        action = "heating active but temperature dropping"
    else:
        action = "cooling active but temperature rising"

    if confidence == "high":
        recommendation = (
            f"{zone_name}: Close window now — {action}, "
            f"{total_change:.1f}°C change over {anomaly_count} readings"
        )
    elif confidence == "medium":
        recommendation = (
            f"{zone_name}: Check windows — {action}, "
            f"{total_change:.1f}°C change detected"
        )
    else:
        recommendation = (
            f"{zone_name}: Verify windows are closed — {action}"
        )

    return WindowPredictedResult(
        detected=True,
        confidence=confidence,
        temp_drop=round(total_change, 2),
        time_window_minutes=time_window_minutes,
        recommendation=recommendation,
        anomaly_readings=anomaly_count,
    )


# ============ Mold Risk Recommendations ============

def calculate_mold_risk_recommendation(
    risk_level: str,
    zone_name: str,
    humidity: Optional[float] = None,
    surface_temp: Optional[float] = None,
    dew_point: Optional[float] = None,
    current_temp: Optional[float] = None,
    target_temp: Optional[float] = None
) -> str:
    """Calculate SMART recommendation for mold risk with delta format.

    Uses delta-first format showing changes needed before absolute
    targets. Includes level transition guidance (e.g. Critical->High).

    FIX: Removed arbitrary min() temperature caps that could
    suggest temperatures below current room temp. When room is already warm
    but surface temp is low (insulation issue), recommends ventilation/
    insulation check instead of pointless heating increase.

    Args:
        risk_level: Current risk level (Critical, High, Medium, Low)
        zone_name: Name of the zone
        humidity: Current humidity percentage
        surface_temp: Calculated surface temperature
        dew_point: Calculated dew point
        current_temp: Current room temperature
        target_temp: Current heating target temperature

    Returns:
        SMART recommendation string (empty if no action needed)
    """
    if risk_level in ("Minimal", "Low"):
        return ""

    # Calculate margin for specific recommendations
    margin = None
    if surface_temp is not None and dew_point is not None:
        margin = round(surface_temp - dew_point, 1)

    # Level transition targets (margin thresholds)
    # Critical (<3) -> High needs margin >= 3
    # High (3-5) -> Medium needs margin >= 5
    # Medium (5-7) -> Low needs margin >= 7

    if risk_level == "Critical":
        # Target: move to High (margin >= 3)
        transition = "Critical\u2192High"
        actions = []
        if humidity and humidity > 70:
            delta_h = round(humidity - 60)
            actions.append(f"reduce humidity by {delta_h}% (from {humidity:.0f}% to <60%)")
        if current_temp and target_temp and current_temp < target_temp:
            delta_t = round(target_temp - current_temp, 1)
            actions.append(f"increase heating by {delta_t}\u00b0C (to {target_temp:.0f}\u00b0C)")
        elif current_temp:
            # Use target_temp as base when available,
            # and guard against suggesting temp <= current_temp
            suggested = (target_temp + 2) if target_temp else (current_temp + 2)
            if suggested <= current_temp:
                # Room already warm — issue is insulation, not heating
                actions.append("check wall/window insulation - room warm but surfaces cold")
            else:
                delta = round(suggested - current_temp, 1)
                actions.append(f"increase heating by +{delta}\u00b0C (to {suggested:.0f}\u00b0C)")

        if actions:
            return f"{zone_name} [{transition}]: URGENT - {' and '.join(actions)}. Ventilate 10 min."
        return f"{zone_name} [{transition}]: URGENT - Ventilate 10 min and increase heating by +2\u00b0C"

    if risk_level == "High":
        # Target: move to Medium (margin >= 5)
        transition = "High\u2192Medium"
        if humidity and humidity > 70:
            delta_h = round(humidity - 55)
            return (
                f"{zone_name} [{transition}]: Humidity {humidity:.0f}% "
                f"(reduce by {delta_h}% to 55%) - dehumidifier or ventilate 15 min"
            )
        if margin is not None and margin < 5:
            needed = round(5 - margin, 1)
            # Use target_temp as base when available,
            # guard against suggesting temp <= current_temp
            base_temp = target_temp if target_temp else current_temp
            if base_temp:
                suggested = base_temp + 1.5
                if current_temp and suggested <= current_temp:
                    # Room already warm — issue is insulation, not heating
                    return (
                        f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                        f"(need +{needed}\u00b0C margin) - improve insulation or ventilate 15 min"
                    )
                return (
                    f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                    f"(need +{needed}\u00b0C margin) - increase heating by +1.5\u00b0C (to {suggested:.0f}\u00b0C)"
                )
        return f"{zone_name} [{transition}]: Ventilate 15 min or increase heating by +1.5\u00b0C"

    if risk_level == "Medium":
        # Target: move to Low (margin >= 7)
        transition = "Medium\u2192Low"
        if humidity and humidity > 65:
            delta_h = round(humidity - 55)
            return (
                f"{zone_name} [{transition}]: Humidity {humidity:.0f}% "
                f"(reduce by {delta_h}% to 55%) - ventilate 10 min after cooking/showering"
            )
        if margin is not None and margin < 7:
            needed = round(7 - margin, 1)
            return (
                f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                f"(need +{needed}\u00b0C margin) - ensure adequate ventilation"
            )
        return f"{zone_name} [{transition}]: Moderate risk - ventilate daily 10 min"

    return ""

# ============ Comfort Level Recommendations ============

def calculate_comfort_recommendation(
    comfort_state: str,
    zone_name: str,
    current_temp: Optional[float] = None,
    target_temp: Optional[float] = None,
    humidity: Optional[float] = None,
    hvac_mode: Optional[str] = None,
    hvac_action: Optional[str] = None
) -> str:
    """Calculate SMART recommendation for comfort level with time frame.

    Added hvac_action parameter to differentiate between
    "heating in progress" vs "heating not reaching target".

    Args:
        comfort_state: Current comfort state (Comfortable, Cold, Cool, etc.)
        zone_name: Name of the zone
        current_temp: Current room temperature
        target_temp: Target/setpoint temperature
        humidity: Current humidity percentage
        hvac_mode: Current HVAC mode (heat, cool, off, auto)
        hvac_action: Current HVAC action (heating, idle, off)

    Returns:
        SMART recommendation string (empty if comfortable)
    """
    if comfort_state == "Comfortable":
        return ""

    # Cold/Cool states
    if comfort_state in ("Too Cold", "Cold", "Cool", "Freezing"):
        if current_temp is not None and target_temp is not None:
            diff = round(target_temp - current_temp, 1)
            if diff > 0:
                if hvac_mode == "off":
                    return (
                        f"{zone_name}: {current_temp:.1f}\u00b0C, "
                        f"target {target_temp:.0f}\u00b0C - turn on heating"
                    )
                # Differentiate based on hvac_action
                if hvac_action == "heating":
                    return (
                        f"{zone_name}: Heating in progress - "
                        f"{current_temp:.1f}\u00b0C, {diff:.1f}\u00b0C below target. "
                        f"Allow 15-30 min to reach {target_temp:.0f}\u00b0C"
                    )
                elif hvac_action in ("idle", "off"):
                    suggested = min(target_temp + 1, 25)
                    return (
                        f"{zone_name}: {current_temp:.1f}\u00b0C, "
                        f"{diff:.1f}\u00b0C below target but heating idle - "
                        f"increase setpoint to {suggested:.0f}\u00b0C"
                    )
                # Unknown hvac_action - generic
                suggested = min(target_temp + 1, 25)
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C, "
                    f"{diff:.1f}\u00b0C below target - "
                    f"increase setpoint to {suggested:.0f}\u00b0C if not warming up"
                )
            else:
                # Remove min() cap that could suggest
                # temp <= current_temp. Use current_temp + 2 directly.
                suggested = current_temp + 2
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C feels cold - "
                    f"set heating to {suggested:.0f}\u00b0C"
                )
        return f"{zone_name}: Room too cold - increase heating setpoint by 2\u00b0C"

    # Hot states
    if comfort_state in ("Too Hot", "Hot", "Warm", "Sweltering"):
        if current_temp is not None:
            if target_temp is not None and current_temp > target_temp:
                over = round(current_temp - target_temp, 1)
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C, "
                    f"{over:.1f}\u00b0C above target - open window or reduce heating"
                )
            suggested = max(current_temp - 2, 18)
            return (
                f"{zone_name}: {current_temp:.1f}\u00b0C too warm - "
                f"reduce setpoint to {suggested:.0f}\u00b0C or open window"
            )
        return f"{zone_name}: Room too hot - reduce heating setpoint by 2\u00b0C or open window"

    if comfort_state == "Too Humid":
        if humidity is not None:
            return (
                f"{zone_name}: Humidity {humidity:.0f}% too high - "
                f"run dehumidifier or ventilate to reach 55%"
            )
        return f"{zone_name}: High humidity - run dehumidifier or open window for 15 minutes"

    if comfort_state == "Too Dry":
        if humidity is not None:
            return (
                f"{zone_name}: Humidity {humidity:.0f}% too low - "
                f"use humidifier to reach 45%"
            )
        return f"{zone_name}: Low humidity - use humidifier or place water bowl near radiator"

    return ""

# ============ Condensation Risk Recommendations ============

def calculate_condensation_recommendation(
    risk_level: str,
    zone_name: str,
    margin: Optional[float] = None,
    ac_setpoint: Optional[float] = None,
    current_temp: Optional[float] = None
) -> str:
    """Calculate SMART recommendation for condensation risk (AC zones).

    Args:
        risk_level: Current risk level (Critical, High, Medium, Low, Minimal)
        zone_name: Name of the zone
        margin: Temperature margin above dew point
        ac_setpoint: Current AC setpoint temperature
        current_temp: Current room temperature

    Returns:
        SMART recommendation string (empty if no action needed)
    """
    if risk_level in ("Minimal", "Low"):
        return ""

    if risk_level == "Critical":
        if ac_setpoint is not None:
            suggested = ac_setpoint + 2
            return (
                f"{zone_name}: URGENT condensation risk - increase AC setpoint "
                f"from {ac_setpoint:.0f}°C to {suggested:.0f}°C immediately"
            )
        return f"{zone_name}: URGENT condensation risk - increase AC setpoint by 2°C and improve ventilation"

    if risk_level == "High":
        if ac_setpoint is not None and margin is not None:
            suggested = ac_setpoint + 1
            return f"{zone_name}: Only {margin:.1f}°C above dew point - increase AC setpoint to {suggested:.0f}°C"
        return f"{zone_name}: High condensation risk - increase AC setpoint by 1°C"

    if risk_level == "Medium":
        if margin is not None:
            return f"{zone_name}: {margin:.1f}°C above dew point - monitor conditions, consider raising AC setpoint"
        return f"{zone_name}: Moderate condensation risk - ensure adequate ventilation"

    return ""


def calculate_heating_condensation_recommendation(
    risk_level: str,
    zone_name: str,
    margin: Optional[float] = None,
    humidity: Optional[float] = None,
    surface_temp: Optional[float] = None,
    dew_point: Optional[float] = None,
) -> str:
    """Calculate SMART recommendation for condensation risk (HEATING zones).

    For heating zones, condensation forms on the INSIDE of windows when
    indoor humidity is high and window inner surface temp drops below
    indoor dew point.

    All values are calculated from current conditions — NO hardcoded
    temperature or humidity thresholds.

    Args:
        risk_level: Current risk level (Critical, High, Medium, Low, None)
        zone_name: Name of the zone
        margin: Temperature margin (surface_temp - dew_point)
        humidity: Current indoor humidity percentage
        surface_temp: Estimated window inner surface temperature
        dew_point: Indoor dew point temperature

    Returns:
        SMART recommendation string (empty if no action needed)
    """
    if risk_level in ("None", "Low"):
        return ""

    if risk_level == "Critical":
        parts = [f"{zone_name}: URGENT — condensation forming on windows"]
        if surface_temp is not None and dew_point is not None and margin is not None:
            parts.append(
                f"Surface temp {surface_temp:.1f}°C is {abs(margin):.1f}°C below dew point {dew_point:.1f}°C"
            )
        parts.append("Open window briefly, use extractor fan, wipe surfaces")
        return ". ".join(parts)

    if risk_level == "High":
        parts = [f"{zone_name}: Windows likely fogging"]
        if margin is not None and dew_point is not None:
            parts.append(
                f"Surface temp only {margin:.1f}°C above dew point {dew_point:.1f}°C"
            )
        parts.append("Ventilate or increase heating")
        return ". ".join(parts)

    if risk_level == "Medium":
        parts = [f"{zone_name}: Monitor — condensation possible"]
        if margin is not None and dew_point is not None:
            parts.append(
                f"Surface temp {margin:.1f}°C above dew point {dew_point:.1f}°C"
            )
        parts.append("Ensure adequate ventilation")
        return ". ".join(parts)

    return ""


# ============ Battery Recommendations ============

def calculate_battery_recommendation(
    battery_state: str,
    zone_name: str,
    device_type: Optional[str] = None
) -> str:
    """Calculate SMART recommendation for battery status.

    Args:
        battery_state: Current battery state (Normal, Low, Critical)
        zone_name: Name of the zone
        device_type: Type of device (TRV, Thermostat, etc.)

    Returns:
        SMART recommendation string (empty if battery is normal)
    """
    if battery_state.upper() == "NORMAL":
        return ""

    # Determine battery type based on device
    battery_type = "AA batteries"
    if device_type:
        device_lower = device_type.lower()
        if "trv" in device_lower or "va0" in device_lower or "ru0" in device_lower:
            battery_type = "2x AA batteries"
        elif "thermostat" in device_lower or "su0" in device_lower:
            battery_type = "3x AAA batteries"

    if battery_state.upper() == "CRITICAL":
        return f"{zone_name}: Replace {battery_type} TODAY - device may stop working"

    if battery_state.upper() == "LOW":
        return f"{zone_name}: Replace {battery_type} within 1-2 weeks"

    return ""


# ============ Connection Recommendations ============

def calculate_connection_recommendation(
    connection_state: str,
    zone_name: str,
    last_seen: Optional[str] = None,
    offline_minutes: Optional[int] = None
) -> str:
    """Calculate SMART recommendation for device connection status.

    Args:
        connection_state: Current connection state (Online, Offline)
        zone_name: Name of the zone
        last_seen: Last seen timestamp string
        offline_minutes: Minutes since device was last seen

    Returns:
        SMART recommendation string (empty if connected)
    """
    if connection_state.upper() == "ONLINE":
        return ""

    if connection_state.upper() == "OFFLINE":
        # Provide time-specific recommendations
        if offline_minutes is not None:
            if offline_minutes < 30:
                return f"{zone_name}: Device offline {offline_minutes} min - may be temporary, wait 30 minutes"
            elif offline_minutes < 120:
                return f"{zone_name}: Device offline {offline_minutes} min - check if device is within 10m of bridge"
            elif offline_minutes < 1440:  # 24 hours
                hours = offline_minutes // 60
                return f"{zone_name}: Device offline {hours}h - check batteries and bridge connection"
            else:
                days = offline_minutes // 1440
                return f"{zone_name}: Device offline {days} days - replace batteries and re-pair if needed"

        if last_seen:
            return f"{zone_name}: Device offline since {last_seen} - check batteries and bridge connection"

        return (
            f"{zone_name}: Device offline - 1) Check batteries "
            "2) Verify bridge is online 3) Move device closer to bridge"
        )

    return ""


# ============ API Status Recommendations ============

def calculate_api_status_recommendation(
    remaining_calls: Optional[int],
    total_calls: Optional[int],
    reset_time_human: Optional[str] = None,
    current_interval_minutes: Optional[int] = None
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

    if usage_percent < 70:
        return ""

    # Calculate suggested interval based on remaining calls and time
    suggested_interval = None
    if current_interval_minutes:
        if usage_percent >= 90:
            suggested_interval = max(current_interval_minutes * 2, 60)
        elif usage_percent >= 80:
            suggested_interval = max(current_interval_minutes + 15, 30)

    reset_info = f" (resets in {reset_time_human})" if reset_time_human else ""

    if usage_percent >= 95:
        return f"API CRITICAL: Only {remaining_calls} calls remaining{reset_info} - pause automations until reset"

    if usage_percent >= 90:
        if suggested_interval:
            return (
                f"API WARNING: {remaining_calls} calls remaining{reset_info}"
                f" - increase polling to {suggested_interval} min"
                " in Settings → Tado CE → Configure"
            )
        return f"API WARNING: {remaining_calls} calls remaining{reset_info} - reduce polling frequency"

    if usage_percent >= 80:
        if suggested_interval:
            return (
                f"API usage at {usage_percent:.0f}%{reset_info}"
                f" - consider increasing polling to {suggested_interval} min"
            )
        return f"API usage at {usage_percent:.0f}%{reset_info} - monitor usage"

    if usage_percent >= 70:
        return f"API usage at {usage_percent:.0f}%{reset_info}"

    return ""




# ============ Historical Deviation Recommendations ============

def calculate_historical_deviation_recommendation(
    deviation: Optional[float],
    zone_name: str,
    current_temp: Optional[float] = None,
    historical_avg: Optional[float] = None,
    sample_count: int = 0
) -> str:
    """Calculate SMART recommendation for historical temperature deviation.

    Args:
        deviation: Temperature difference from historical average (degrees C)
        zone_name: Name of the zone
        current_temp: Current room temperature
        historical_avg: 7-day average temperature at this time
        sample_count: Number of historical samples used

    Returns:
        SMART recommendation string (empty if deviation is normal)
    """
    if deviation is None or sample_count < 3:
        return ""

    abs_deviation = abs(deviation)

    # Normal range: within 1.5 degrees C of historical average
    if abs_deviation <= 1.5:
        return ""

    if deviation > 3.0:
        if current_temp is not None and historical_avg is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C warmer than usual "
                f"({current_temp:.1f}°C vs avg {historical_avg:.1f}°C) "
                f"- check if heating schedule needs adjustment"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C warmer than usual - review heating schedule"

    if deviation > 1.5:
        if current_temp is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C above average "
                f"({current_temp:.1f}°C) - monitor for pattern"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C above average - monitor for pattern"

    if deviation < -3.0:
        if current_temp is not None and historical_avg is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C colder than usual "
                f"({current_temp:.1f}°C vs avg {historical_avg:.1f}°C) "
                f"- check windows and heating system"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C colder than usual - check windows and heating"

    if deviation < -1.5:
        if current_temp is not None:
            return (
                f"{zone_name}: {abs_deviation:.1f}°C below average "
                f"({current_temp:.1f}°C) - check for drafts or open windows"
            )
        return f"{zone_name}: {abs_deviation:.1f}°C below average - check for drafts"

    return ""


# ============ Analysis Confidence Recommendations ============

def calculate_confidence_recommendation(
    confidence_percent: Optional[float],
    zone_name: str,
    cycle_count: int = 0,
    completed_count: int = 0
) -> str:
    """Calculate SMART recommendation for thermal analysis confidence.

    Args:
        confidence_percent: Confidence score as percentage (0-100)
        zone_name: Name of the zone
        cycle_count: Total heating cycles detected
        completed_count: Completed heating cycles analyzed

    Returns:
        SMART recommendation string (empty if confidence is adequate)
    """
    if confidence_percent is None:
        return ""

    if confidence_percent >= 70:
        return ""

    if confidence_percent < 30:
        needed = max(5 - completed_count, 1)
        return (
            f"{zone_name}: Low analysis confidence ({confidence_percent:.0f}%) "
            f"- need {needed} more complete heating cycles for reliable estimates"
        )

    if confidence_percent < 50:
        needed = max(3 - completed_count, 1)
        return (
            f"{zone_name}: Moderate confidence ({confidence_percent:.0f}%) "
            f"- {needed} more heating cycles will improve preheat accuracy"
        )

    # 50-70%
    return (
        f"{zone_name}: Building confidence ({confidence_percent:.0f}%) "
        f"- estimates improving with each heating cycle"
    )

# ============ Home Insights Aggregation ============

def get_insight_priority(insight_type: str, severity: str) -> InsightPriority:
    """Get priority level for an insight based on type and severity.

    Args:
        insight_type: Type of insight (window_predicted, mold_risk, etc.)
        severity: Severity level (critical, high, medium, low)

    Returns:
        InsightPriority enum value
    """
    priority_map = {
        # Existing insights
        ("window_predicted", "high"): InsightPriority.HIGH,
        ("window_predicted", "medium"): InsightPriority.MEDIUM,
        ("window_predicted", "low"): InsightPriority.LOW,
        ("mold_risk", "critical"): InsightPriority.CRITICAL,
        ("mold_risk", "high"): InsightPriority.HIGH,
        ("mold_risk", "medium"): InsightPriority.MEDIUM,
        ("condensation", "critical"): InsightPriority.CRITICAL,
        ("condensation", "high"): InsightPriority.HIGH,
        ("condensation", "medium"): InsightPriority.MEDIUM,
        ("connection", "offline"): InsightPriority.HIGH,
        ("connection", "offline_long"): InsightPriority.CRITICAL,
        ("battery", "critical"): InsightPriority.CRITICAL,
        ("battery", "low"): InsightPriority.HIGH,
        ("comfort", "too_cold"): InsightPriority.MEDIUM,
        ("comfort", "too_hot"): InsightPriority.MEDIUM,
        ("api", "critical"): InsightPriority.CRITICAL,
        ("api", "warning"): InsightPriority.HIGH,
        ("api", "high"): InsightPriority.MEDIUM,
        # Category A — Overlay & Schedule
        ("overlay_duration", "medium"): InsightPriority.MEDIUM,
        ("overlay_duration", "low"): InsightPriority.LOW,
        ("schedule_gap", "medium"): InsightPriority.MEDIUM,
        ("frequent_override", "low"): InsightPriority.LOW,
        # Category B — Home/Away Presence
        ("away_heating", "high"): InsightPriority.HIGH,
        ("home_all_off", "medium"): InsightPriority.MEDIUM,
        # Category C — Weather & Outdoor
        ("solar_gain", "low"): InsightPriority.LOW,
        ("solar_ac_load", "low"): InsightPriority.LOW,
        ("frost_risk", "high"): InsightPriority.HIGH,
        ("frost_risk", "medium"): InsightPriority.MEDIUM,
        ("heating_season", "low"): InsightPriority.LOW,
        # Category D — Heating/AC Efficiency
        ("heating_off_cold", "medium"): InsightPriority.MEDIUM,
        ("boiler_flow_anomaly", "high"): InsightPriority.HIGH,
        ("boiler_flow_anomaly", "medium"): InsightPriority.MEDIUM,
        ("early_start_disabled", "low"): InsightPriority.LOW,
        ("thermal_efficiency", "medium"): InsightPriority.MEDIUM,
        # Category E — Cross-Zone
        ("cross_zone_condensation", "high"): InsightPriority.HIGH,
        ("cross_zone_efficiency", "low"): InsightPriority.LOW,
        ("temp_imbalance", "low"): InsightPriority.LOW,
        ("humidity_imbalance", "medium"): InsightPriority.MEDIUM,
        # Category F — Environment Trends
        ("humidity_trend", "medium"): InsightPriority.MEDIUM,
        # Category G — Device & System
        ("device_limitation", "low"): InsightPriority.LOW,
        ("geofencing_offline", "medium"): InsightPriority.MEDIUM,
        ("api_usage_spike", "medium"): InsightPriority.MEDIUM,
    }
    return priority_map.get((insight_type, severity.lower()), InsightPriority.NONE)


def _get_action_label(insight_type: str) -> str:
    """Map insight_type to a user-friendly action label for grouping."""
    action_map = {
        # Device & maintenance
        "battery": "Replace batteries",
        "connection": "Check device connection",
        # Comfort & environment
        "mold_risk": "Improve ventilation (mold risk)",
        "condensation": "Reduce condensation risk",
        "comfort": "Review comfort settings",
        "humidity_trend": "Monitor humidity trend",
        "humidity_imbalance": "Balance humidity across zones",
        # Heating efficiency
        "thermal_efficiency": "Check heating efficiency",
        "heating_anomaly": "Investigate heating anomaly",
        "heating_off_cold": "Turn on heating (zone too cold)",
        "boiler_flow_anomaly": "Check boiler flow temperature",
        "cross_zone_efficiency": "Improve cross-zone efficiency",
        "cross_zone_condensation": "Address cross-zone condensation",
        # Schedule & overrides
        "frequent_override": "Review permanent overrides",
        "overlay_duration": "Check long-running overlays",
        "schedule_deviation": "Review schedule deviation",
        "schedule_gap": "Fill schedule gaps",
        "early_start_disabled": "Enable early start",
        # Preheat & timing
        "preheat_timing": "Adjust preheat timing",
        # Weather & environment
        "weather_impact": "Weather affecting heating",
        "frost_risk": "Frost protection needed",
        "solar_gain": "Solar gain detected",
        "solar_ac_load": "Solar increasing AC load",
        "heating_season": "Heating season advisory",
        "temp_imbalance": "Balance temperatures across zones",
        # Window
        "window_predicted": "Close window (heat loss detected)",
        "cross_zone_window": "Multiple windows open",
        "cross_zone_mold": "Mold risk across multiple zones",
        # System
        "away_heating": "Heating active while away",
        "home_all_off": "All zones off while home",
        "api_quota_planning": "Review API quota usage",
        "api_usage_spike": "API usage spike detected",
        "geofencing_offline": "Check geofencing status",
        "device_limitation": "Device limitation detected",
    }
    return action_map.get(insight_type, insight_type.replace("_", " ").title())


def aggregate_home_insights(zone_insights: dict[str, list[Insight]]) -> dict:
    """Aggregate insights from all zones into action-based home summary.

    Groups insights by action type across zones, producing a list of
    actionable items like "Replace batteries: Guest, Lounge" instead of
    raw priority counts.

    Args:
        zone_insights: Dict mapping zone names to lists of Insight objects

    Returns:
        Dict with action-based aggregated insights
    """
    empty_result = {
        "total_insights": 0,
        "top_priority": "none",
        "top_recommendation": "",
        "summary": "All zones are running well — no issues detected.",
        "actions_needed": [],
        "zones_ok": [],
        "zones_with_issues": [],
    }
    if not zone_insights:
        return empty_result

    all_insights: list[Insight] = []
    zones_with_issues: list[str] = []
    all_zone_names: set[str] = set()

    for zone_name, insights in zone_insights.items():
        if zone_name.startswith("_"):
            # Hub-level insights (e.g. "_hub") — no zone name to track
            all_insights.extend(insights)
            continue
        all_zone_names.add(zone_name)
        if insights:
            zones_with_issues.append(zone_name)
            all_insights.extend(insights)

    if not all_insights:
        empty_result["zones_ok"] = sorted(all_zone_names)
        return empty_result

    # Group by action label, tracking zones and max priority per action
    action_groups: dict[str, dict] = {}
    for insight in all_insights:
        label = _get_action_label(insight.insight_type)
        if label not in action_groups:
            action_groups[label] = {"zones": [], "priority": insight.priority}
        grp = action_groups[label]
        if insight.zone_name and insight.zone_name not in grp["zones"]:
            grp["zones"].append(insight.zone_name)
        if insight.priority > grp["priority"]:
            grp["priority"] = insight.priority

    # Sort actions by priority (highest first), then alphabetically
    sorted_actions = sorted(
        action_groups.items(),
        key=lambda x: (-x[1]["priority"], x[0]),
    )

    # Build actions_needed list: "Action: Zone1, Zone2" or just "Action" for cross-zone
    actions_needed = []
    for label, grp in sorted_actions:
        if grp["zones"]:
            actions_needed.append(f"{label}: {', '.join(grp['zones'])}")
        else:
            actions_needed.append(label)

    # Find top priority
    top_insight = max(all_insights, key=lambda i: i.priority)
    top_priority = top_insight.priority.name.lower()
    top_recommendation = top_insight.recommendation

    # Zones with no issues
    zones_ok = sorted(all_zone_names - set(zones_with_issues))

    # Build summary sentence
    n_actions = len(actions_needed)
    n_zones = len(zones_with_issues)
    if n_actions == 1:
        summary = f"1 action needed across {n_zones} zone{'s' if n_zones != 1 else ''}."
    else:
        summary = f"{n_actions} actions needed across {n_zones} zone{'s' if n_zones != 1 else ''}."

    return {
        "total_insights": len(all_insights),
        "top_priority": top_priority,
        "top_recommendation": top_recommendation,
        "summary": summary,
        "actions_needed": actions_needed,
        "zones_ok": zones_ok,
        "zones_with_issues": sorted(zones_with_issues),
    }


# ============ Preheat Timing Insight (US-14) ============

def calculate_preheat_timing_insight(
    preheat_time_minutes: Optional[float] = None,
    next_schedule_time: Optional[str] = None,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Calculate preheat timing insight.

    Combines Thermal Analytics preheat_time with Smart Comfort
    next_schedule_time to advise when preheating should start.

    Args:
        preheat_time_minutes: Estimated preheat time in minutes
        next_schedule_time: Next schedule change time (ISO format or HH:MM)
        zone_name: Name of the zone

    Returns:
        Insight if preheat timing is relevant, None otherwise
    """
    if preheat_time_minutes is None or next_schedule_time is None:
        return None

    if preheat_time_minutes <= 0:
        return None

    # Parse time string
    time_str = str(next_schedule_time)
    rec = (
        f"{zone_name}: Preheat takes ~{preheat_time_minutes:.0f} min. "
        f"Next schedule change at {time_str} - "
        f"start heating {preheat_time_minutes:.0f} min before."
    )

    priority = InsightPriority.LOW
    if preheat_time_minutes > 30:
        priority = InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="preheat_timing",
        zone_name=zone_name,
    )


# ============ Schedule Deviation Insight (US-15) ============

def calculate_schedule_deviation_insight(
    historical_temp: Optional[float] = None,
    target_temp: Optional[float] = None,
    deviation_days: int = 0,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Detect consistent schedule deviation over multiple days.

    Triggers when actual temperature consistently deviates from target
    for 3+ days, suggesting the schedule may need adjustment.

    Args:
        historical_temp: Average actual temperature over recent days
        target_temp: Scheduled target temperature
        deviation_days: Number of consecutive days with deviation
        zone_name: Name of the zone

    Returns:
        Insight if deviation is consistent, None otherwise
    """
    if historical_temp is None or target_temp is None:
        return None
    if deviation_days < 3:
        return None

    diff = round(historical_temp - target_temp, 1)
    if abs(diff) < 1.0:
        return None

    if diff > 0:
        rec = (
            f"{zone_name}: Actual temp {historical_temp:.1f}\u00b0C has been "
            f"+{diff:.1f}\u00b0C above schedule target ({target_temp:.0f}\u00b0C) "
            f"for {deviation_days} days - consider lowering schedule by {abs(diff):.0f}\u00b0C"
        )
    else:
        rec = (
            f"{zone_name}: Actual temp {historical_temp:.1f}\u00b0C has been "
            f"{diff:.1f}\u00b0C below schedule target ({target_temp:.0f}\u00b0C) "
            f"for {deviation_days} days - consider raising schedule by {abs(diff):.0f}\u00b0C"
        )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="schedule_deviation",
        zone_name=zone_name,
    )


# ============ Heating Power Anomaly Detection (US-16) ============

def calculate_heating_anomaly_insight(
    heating_power_pct: Optional[float] = None,
    temp_delta: Optional[float] = None,
    duration_minutes: int = 0,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Detect heating power anomaly.

    Triggers when heating_power >= 80% AND temp_delta < 0.5C for 60+ min,
    indicating the heating system may not be working effectively.

    Args:
        heating_power_pct: Current heating power percentage (0-100)
        temp_delta: Temperature change over the monitoring period
        duration_minutes: How long the condition has persisted
        zone_name: Name of the zone

    Returns:
        Insight with HIGH priority if anomaly detected, None otherwise
    """
    if heating_power_pct is None or temp_delta is None:
        return None
    if duration_minutes < 60:
        return None
    if heating_power_pct < 80 or temp_delta >= 0.5:
        return None

    hours = duration_minutes / 60
    rec = (
        f"{zone_name}: Heating at {heating_power_pct:.0f}% for {hours:.1f}h "
        f"but temp only changed {temp_delta:.1f}\u00b0C - "
        f"check TRV/radiator for blockage or air lock"
    )

    return Insight(
        priority=InsightPriority.HIGH,
        recommendation=rec,
        insight_type="heating_anomaly",
        zone_name=zone_name,
    )


# ============ Cross-Zone Mold Risk Aggregation (US-17) ============

def aggregate_cross_zone_mold_risk(
    zone_mold_risks: dict[str, str],
) -> Optional["Insight"]:
    """Aggregate mold risk across zones.

    Triggers when 3+ zones have Medium/High/Critical mold risk,
    suggesting a whole-house humidity problem.

    Args:
        zone_mold_risks: Dict mapping zone names to risk levels

    Returns:
        Insight if whole-house issue detected, None otherwise
    """
    if not zone_mold_risks:
        return None

    affected = [
        name for name, level in zone_mold_risks.items()
        if level in ("Medium", "High", "Critical")
    ]

    if len(affected) < 3:
        return None

    zones_str = ", ".join(affected[:5])
    rec = (
        f"Whole-house mold risk: {len(affected)} zones affected "
        f"({zones_str}) - consider whole-house dehumidifier or "
        f"check ventilation system"
    )

    # Priority based on worst zone
    has_critical = any(
        zone_mold_risks[z] == "Critical" for z in affected
    )
    priority = InsightPriority.CRITICAL if has_critical else InsightPriority.HIGH

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="cross_zone_mold",
        zone_name=None,
    )


# ============ Cross-Zone Window Detection (US-18) ============

def aggregate_cross_zone_window_predicted(
    zone_window_states: dict[str, bool],
) -> Optional["Insight"]:
    """Aggregate window predicted across zones.

    Triggers when 2+ zones have window_predicted=on,
    suggesting multiple windows are open simultaneously.

    Args:
        zone_window_states: Dict mapping zone names to window predicted state

    Returns:
        Insight if multiple windows detected, None otherwise
    """
    if not zone_window_states:
        return None

    open_zones = [name for name, is_open in zone_window_states.items() if is_open]

    if len(open_zones) < 2:
        return None

    zones_str = ", ".join(open_zones)
    rec = (
        f"Multiple windows detected open: {zones_str} - "
        f"close windows to prevent energy waste"
    )

    return Insight(
        priority=InsightPriority.HIGH,
        recommendation=rec,
        insight_type="cross_zone_window",
        zone_name=None,
    )


# ============ API Quota Planning Insight (US-19) ============

def calculate_api_quota_planning_insight(
    remaining_calls: Optional[int] = None,
    total_calls: Optional[int] = None,
    calls_per_hour: Optional[float] = None,
    hours_until_reset: Optional[float] = None,
    current_interval_minutes: Optional[float] = None,
) -> Optional["Insight"]:
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
    if buffer_hours < 6:
        return None

    # Suggest new interval
    if hours_until_reset > 0 and remaining_calls > 0:
        safe_calls_per_hour = remaining_calls / hours_until_reset * 0.8  # 20% safety margin
        if safe_calls_per_hour > 0:
            suggested_interval = max(60 / safe_calls_per_hour, 5)  # min 5 minutes
        else:
            suggested_interval = 30
    else:
        suggested_interval = 30

    rec = (
        f"API quota: {remaining_calls} calls left, "
        f"projected to run out {buffer_hours:.0f}h before reset. "
        f"Consider increasing polling interval to {suggested_interval:.0f} min"
    )

    priority = InsightPriority.HIGH if buffer_hours > 12 else InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="api_quota_planning",
        zone_name=None,
    )


# ============ Weather Impact Insight (US-20) ============

def calculate_weather_impact_insight(
    current_outdoor_temp: Optional[float] = None,
    avg_outdoor_temp_7d: Optional[float] = None,
    zone_name: str = "",
) -> Optional["Insight"]:
    """Calculate weather impact insight.

    Triggers when current outdoor temp is > 5C colder than 7-day average,
    estimating increased heating demand.

    Args:
        current_outdoor_temp: Current outdoor temperature
        avg_outdoor_temp_7d: 7-day average outdoor temperature
        zone_name: Name of the zone (or empty for home-level)

    Returns:
        Insight if significant weather impact, None otherwise
    """
    if current_outdoor_temp is None or avg_outdoor_temp_7d is None:
        return None

    diff = round(avg_outdoor_temp_7d - current_outdoor_temp, 1)
    if diff <= 5.0:
        return None

    # Rough estimate: each 1C drop increases heating by ~3-5%
    impact_pct = round(diff * 4)  # ~4% per degree

    rec = (
        f"Cold snap: {current_outdoor_temp:.0f}\u00b0C outdoor, "
        f"{diff:.0f}\u00b0C below 7-day average. "
        f"Estimated {impact_pct}% increase in heating demand"
    )

    priority = InsightPriority.LOW
    if diff > 10:
        priority = InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="weather_impact",
        zone_name=zone_name if zone_name else None,
    )

# ============ Dew Point Calculation (moved from sensor.py) ============

def calculate_dew_point(temperature: float, humidity: float) -> float:
    """Calculate dew point using Magnus-Tetens formula.

    Formula: Td = (b × α) / (a - α)
    where α = (a × T) / (b + T) + ln(RH/100)

    Constants (for -40°C to 50°C range):
    a = 17.27, b = 237.7°C

    Args:
        temperature: Indoor temperature in °C
        humidity: Relative humidity in %

    Returns:
        Dew point temperature in °C
    """
    a = 17.27
    b = 237.7
    # Clamp humidity to valid range (avoid log(0))
    humidity = max(1, min(100, humidity))
    alpha = (a * temperature) / (b + temperature) + math.log(humidity / 100)
    return round((b * alpha) / (a - alpha), 1)


# ============ Mold Risk Level Classification ============

def classify_mold_risk_level(inside_temp: float, humidity: float) -> str:
    """Classify mold risk level from temperature and humidity.

    Uses dew point margin thresholds:
    - Critical: margin < 3°C
    - High:     margin < 5°C
    - Medium:   margin < 7°C
    - Low:      margin >= 7°C

    Args:
        inside_temp: Indoor temperature in °C
        humidity: Relative humidity in %

    Returns:
        Risk level string: "Critical", "High", "Medium", or "Low"
    """
    dew_point = calculate_dew_point(inside_temp, humidity)
    margin = round(inside_temp - dew_point, 1)
    if margin < 3:
        return "Critical"
    if margin < 5:
        return "High"
    if margin < 7:
        return "Medium"
    return "Low"


# ============ Comfort Level Classification ============

def classify_comfort_level(inside_temp: float) -> str:
    """Classify comfort level from indoor temperature.

    Thresholds:
    - Cold:        < 16°C
    - Cool:        < 18°C
    - Comfortable: <= 24°C
    - Warm:        <= 26°C
    - Hot:         > 26°C

    Args:
        inside_temp: Indoor temperature in °C

    Returns:
        Comfort level string: "Cold", "Cool", "Comfortable", "Warm", or "Hot"
    """
    if inside_temp < 16:
        return "Cold"
    if inside_temp < 18:
        return "Cool"
    if inside_temp <= 24:
        return "Comfortable"
    if inside_temp <= 26:
        return "Warm"
    return "Hot"


# ============ API Call Rate Calculation ============

def calculate_calls_per_hour(history: list) -> Optional[float]:
    """Calculate average API calls per hour from call history.

    Args:
        history: List of call history dicts with "timestamp" key (ISO format)

    Returns:
        Calls per hour as float, or None if insufficient data
    """
    if not history or len(history) < 2:
        return None
    try:
        first_ts = history[0].get("timestamp", "")
        last_ts = history[-1].get("timestamp", "")
        first_dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        hours_span = (last_dt - first_dt).total_seconds() / 3600
        if hours_span <= 0:
            return None
        return len(history) / hours_span
    except (ValueError, TypeError, AttributeError):
        return None

# ============================================================================
# Category A (Overlay & Schedule)
# ============================================================================


def calculate_overlay_duration_insight(
    overlay_type: Optional[str] = None,
    next_schedule_change: Optional[str] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Detect permanent manual overlay that user may have forgotten.

    Triggers when overlayType is present but nextScheduleChange is null,
    meaning the overlay will persist indefinitely until manually cancelled.

    Args:
        overlay_type: Current overlay type (MANUAL, etc.) or None
        next_schedule_change: Next schedule change time, or None if permanent
        zone_name: Name of the zone

    Returns:
        Insight if permanent overlay detected, None otherwise
    """
    if not overlay_type:
        return None
    # Timer-based overlays have a nextScheduleChange — not a concern
    if next_schedule_change is not None:
        return None

    rec = (
        f"{zone_name}: Manual override ({overlay_type}) is set to permanent "
        f"- it will stay until you cancel it. Review if this is intentional."
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="overlay_duration",
        zone_name=zone_name,
    )


def calculate_schedule_gap_insight(
    schedule_blocks: Optional[list] = None,
    current_temp: Optional[float] = None,
    next_target_temp: Optional[float] = None,
    longest_off_hours: Optional[float] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Detect long OFF gaps in schedule while room is cold.

    Triggers when the schedule has a long continuous OFF period and the
    current room temperature is below the next scheduled target.

    Args:
        schedule_blocks: List of schedule block dicts (not used directly,
            but indicates schedule exists)
        current_temp: Current room temperature
        next_target_temp: Next scheduled target temperature
        longest_off_hours: Duration of longest OFF period in hours
        zone_name: Name of the zone

    Returns:
        Insight if significant gap found, None otherwise
    """
    if schedule_blocks is None or current_temp is None:
        return None
    if next_target_temp is None or longest_off_hours is None:
        return None
    if longest_off_hours < 6:
        return None

    temp_deficit = next_target_temp - current_temp
    if temp_deficit < 2.0:
        return None

    rec = (
        f"{zone_name}: Schedule has a {longest_off_hours:.0f}h OFF gap and "
        f"room is {current_temp:.1f}\u00b0C ({temp_deficit:.1f}\u00b0C below "
        f"next target {next_target_temp:.0f}\u00b0C) - consider adding a "
        f"setback temperature to prevent deep cooling"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="schedule_gap",
        zone_name=zone_name,
    )


def calculate_frequent_override_insight(
    overlay_type: Optional[str] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Suggest schedule review when manual override is active.

    Simple insight that triggers whenever an overlay is active,
    reminding the user to consider adjusting their schedule.

    Args:
        overlay_type: Current overlay type or None
        zone_name: Name of the zone

    Returns:
        Insight if overlay active, None otherwise
    """
    if not overlay_type:
        return None

    rec = (
        f"{zone_name}: Currently on manual override ({overlay_type}) "
        f"- if you override often, consider adjusting the schedule "
        f"to match your routine"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="frequent_override",
        zone_name=zone_name,
    )



# ============================================================================
# Category B (Home/Away Presence)
# ============================================================================


def calculate_away_heating_active_insight(
    presence: Optional[str] = None,
    active_zones: Optional[list] = None,
) -> Optional[Insight]:
    """Detect energy waste: home is AWAY but zones still heating/cooling.

    Args:
        presence: Home presence state ("HOME", "AWAY", etc.)
        active_zones: List of dicts with keys: zone_name, power_pct, zone_type
            Only zones with power > 0 should be included.

    Returns:
        Insight if AWAY with active heating/cooling, None otherwise
    """
    if presence is None or presence.upper() != "AWAY":
        return None
    if not active_zones:
        return None

    zone_descs = []
    for z in active_zones[:5]:
        name = z.get("zone_name", "Unknown")
        pct = z.get("power_pct", 0)
        zone_descs.append(f"{name} ({pct:.0f}%)")

    zones_str = ", ".join(zone_descs)
    rec = (
        f"Home is AWAY but {len(active_zones)} zone(s) still active: "
        f"{zones_str} - check if this is intentional"
    )

    return Insight(
        priority=InsightPriority.HIGH,
        recommendation=rec,
        insight_type="away_heating",
        zone_name=None,
    )


def calculate_home_all_off_insight(
    presence: Optional[str] = None,
    all_zones_off: bool = True,
    coldest_zone_name: Optional[str] = None,
    coldest_zone_temp: Optional[float] = None,
    coldest_zone_target: Optional[float] = None,
) -> Optional[Insight]:
    """Detect when someone is home but all heating is off and rooms are cold.

    Args:
        presence: Home presence state
        all_zones_off: Whether all zones have power=OFF
        coldest_zone_name: Name of the coldest zone
        coldest_zone_temp: Temperature of the coldest zone
        coldest_zone_target: Scheduled target of the coldest zone

    Returns:
        Insight if HOME with all zones off and cold, None otherwise
    """
    if presence is None or presence.upper() != "HOME":
        return None
    if not all_zones_off:
        return None
    if coldest_zone_temp is None or coldest_zone_target is None:
        return None

    deficit = coldest_zone_target - coldest_zone_temp
    if deficit < 2.0:
        return None

    rec = (
        f"Someone is home but all heating is off. "
        f"{coldest_zone_name}: {coldest_zone_temp:.1f}\u00b0C "
        f"({deficit:.1f}\u00b0C below target {coldest_zone_target:.0f}\u00b0C)"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="home_all_off",
        zone_name=None,
    )



# ============================================================================
# Category C (Weather & Outdoor)
# ============================================================================


def calculate_solar_gain_insight(
    solar_intensity_pct: Optional[float] = None,
    heating_zones_active: Optional[list] = None,
) -> Optional[Insight]:
    """Suggest leveraging solar gain when sun is strong and heating is active.

    Args:
        solar_intensity_pct: Solar intensity percentage (0-100)
        heating_zones_active: List of dicts with keys: zone_name, power_pct
            Only heating zones with power > 0.

    Returns:
        Insight if solar gain opportunity exists, None otherwise
    """
    if solar_intensity_pct is None or solar_intensity_pct < 60:
        return None
    if not heating_zones_active:
        return None

    zone_names = [z.get("zone_name", "") for z in heating_zones_active[:3]]
    zones_str = ", ".join(zone_names)
    rec = (
        f"Solar intensity is {solar_intensity_pct:.0f}% while heating is "
        f"active in {zones_str} - open curtains to leverage solar gain "
        f"and consider reducing target temperature"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="solar_gain",
        zone_name=None,
    )


def calculate_solar_ac_load_insight(
    solar_intensity_pct: Optional[float] = None,
    ac_zones_active: Optional[list] = None,
) -> Optional[Insight]:
    """Warn about solar load increasing AC demand.

    Args:
        solar_intensity_pct: Solar intensity percentage (0-100)
        ac_zones_active: List of dicts with keys: zone_name

    Returns:
        Insight if solar load is increasing AC demand, None otherwise
    """
    if solar_intensity_pct is None or solar_intensity_pct < 60:
        return None
    if not ac_zones_active:
        return None

    zone_names = [z.get("zone_name", "") for z in ac_zones_active[:3]]
    zones_str = ", ".join(zone_names)
    rec = (
        f"Solar intensity is {solar_intensity_pct:.0f}% while AC is active "
        f"in {zones_str} - close blinds/curtains to reduce cooling demand"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="solar_ac_load",
        zone_name=None,
    )


def calculate_frost_risk_insight(
    outdoor_temp: Optional[float] = None,
) -> Optional[Insight]:
    """Warn about frost/pipe freezing risk when outdoor temp near freezing.

    Args:
        outdoor_temp: Current outdoor temperature in °C

    Returns:
        Insight if frost risk detected, None otherwise
    """
    if outdoor_temp is None:
        return None
    if outdoor_temp > 3.0:
        return None

    if outdoor_temp <= 0:
        rec = (
            f"Outdoor temperature is {outdoor_temp:.1f}\u00b0C (below freezing) "
            f"- ensure heating is not fully off to prevent pipe freezing"
        )
        priority = InsightPriority.HIGH
    else:
        rec = (
            f"Outdoor temperature is {outdoor_temp:.1f}\u00b0C (approaching "
            f"freezing) - monitor heating to prevent pipe freezing risk"
        )
        priority = InsightPriority.MEDIUM

    return Insight(
        priority=priority,
        recommendation=rec,
        insight_type="frost_risk",
        zone_name=None,
    )


def calculate_heating_season_advisory_insight(
    current_avg_7d: Optional[float] = None,
    previous_avg_7d: Optional[float] = None,
) -> Optional[Insight]:
    """Advise on seasonal heating changes based on outdoor temp trends.

    Compares current 7-day average to previous 7-day average to detect
    significant warming or cooling trends.

    Args:
        current_avg_7d: Current 7-day average outdoor temperature
        previous_avg_7d: Previous 7-day average outdoor temperature

    Returns:
        Insight if significant seasonal trend detected, None otherwise
    """
    if current_avg_7d is None or previous_avg_7d is None:
        return None

    diff = round(current_avg_7d - previous_avg_7d, 1)
    if abs(diff) < 3.0:
        return None

    if diff > 0:
        rec = (
            f"Outdoor temps warming: 7-day avg {current_avg_7d:.1f}\u00b0C "
            f"(+{diff:.1f}\u00b0C vs previous week) - consider reducing "
            f"heating schedules as weather improves"
        )
    else:
        rec = (
            f"Outdoor temps cooling: 7-day avg {current_avg_7d:.1f}\u00b0C "
            f"({diff:.1f}\u00b0C vs previous week) - consider increasing "
            f"heating schedules as weather gets colder"
        )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="heating_season",
        zone_name=None,
    )



# ============================================================================
# Category D (Heating/AC Efficiency)
# ============================================================================


def calculate_heating_off_cold_room_insight(
    power_state: Optional[str] = None,
    current_temp: Optional[float] = None,
    target_temp: Optional[float] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Detect when heating is OFF but room has dropped significantly below target.

    Args:
        power_state: Zone power state ("ON", "OFF")
        current_temp: Current room temperature
        target_temp: Last known or scheduled target temperature
        zone_name: Name of the zone

    Returns:
        Insight if room is cold with heating off, None otherwise
    """
    if power_state is None or power_state.upper() != "OFF":
        return None
    if current_temp is None or target_temp is None:
        return None

    deficit = target_temp - current_temp
    if deficit < 3.0:
        return None

    rec = (
        f"{zone_name}: Heating is OFF but room is {current_temp:.1f}\u00b0C "
        f"({deficit:.1f}\u00b0C below target {target_temp:.0f}\u00b0C) "
        f"- consider turning heating back on"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="heating_off_cold",
        zone_name=zone_name,
    )


def calculate_boiler_flow_anomaly_insight(
    flow_temp: Optional[float] = None,
    heating_power_pct: Optional[float] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Detect boiler flow temperature anomaly relative to heating demand.

    Triggers when flow temp is high but heating demand is low, or
    flow temp is low but heating demand is high.

    Args:
        flow_temp: Boiler flow temperature in °C
        heating_power_pct: Current heating power percentage (0-100)
        zone_name: Name of the zone (or empty for hub-level)

    Returns:
        Insight if flow temp anomaly detected, None otherwise
    """
    if flow_temp is None or heating_power_pct is None:
        return None

    # High flow temp but low demand
    if flow_temp > 60 and heating_power_pct < 20:
        rec = (
            f"Boiler flow temp is {flow_temp:.0f}\u00b0C but heating demand "
            f"is only {heating_power_pct:.0f}% - flow temperature may be "
            f"set too high, consider lowering for efficiency"
        )
        return Insight(
            priority=InsightPriority.MEDIUM,
            recommendation=rec,
            insight_type="boiler_flow_anomaly",
            zone_name=zone_name if zone_name else None,
        )

    # Low flow temp but high demand
    if flow_temp < 30 and heating_power_pct > 80:
        rec = (
            f"Boiler flow temp is only {flow_temp:.0f}\u00b0C but heating "
            f"demand is {heating_power_pct:.0f}% - boiler may not be "
            f"firing correctly, check boiler status"
        )
        return Insight(
            priority=InsightPriority.HIGH,
            recommendation=rec,
            insight_type="boiler_flow_anomaly",
            zone_name=zone_name if zone_name else None,
        )

    return None


def calculate_early_start_disabled_insight(
    early_start_enabled: bool = True,
    preheat_time_minutes: Optional[float] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Suggest enabling Early Start when preheat time is long.

    Args:
        early_start_enabled: Whether Early Start switch is ON
        preheat_time_minutes: Estimated preheat time from Thermal Analytics
        zone_name: Name of the zone

    Returns:
        Insight if Early Start disabled with long preheat, None otherwise
    """
    if early_start_enabled:
        return None
    if preheat_time_minutes is None or preheat_time_minutes < 30:
        return None

    rec = (
        f"{zone_name}: Early Start is disabled but preheat takes "
        f"~{preheat_time_minutes:.0f} min - enable Early Start so the "
        f"room is warm when your schedule starts"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="early_start_disabled",
        zone_name=zone_name,
    )


def calculate_poor_thermal_efficiency_insight(
    thermal_inertia: Optional[float] = None,
    heating_rate: Optional[float] = None,
    confidence_score: Optional[float] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Detect poor thermal efficiency from Thermal Analytics data.

    Triggers when thermal inertia is high or heating rate is very low,
    suggesting insulation or radiator issues.

    Args:
        thermal_inertia: Thermal inertia in minutes
        heating_rate: Heating rate in °C/hour
        confidence_score: Analysis confidence (0.0-1.0)
        zone_name: Name of the zone

    Returns:
        Insight if poor efficiency detected, None otherwise
    """
    if confidence_score is not None and confidence_score < 0.5:
        return None

    if thermal_inertia is None and heating_rate is None:
        return None

    issues = []
    if thermal_inertia is not None and thermal_inertia > 60:
        issues.append(f"thermal inertia is {thermal_inertia:.0f} min (high)")
    if heating_rate is not None and heating_rate < 0.5:
        issues.append(f"heating rate is {heating_rate:.2f}\u00b0C/h (slow)")

    if not issues:
        return None

    issues_str = " and ".join(issues)
    rec = (
        f"{zone_name}: {issues_str} - check insulation, "
        f"radiator sizing, or TRV operation"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="thermal_efficiency",
        zone_name=zone_name,
    )



# ============================================================================
# Category E (Cross-Zone)
# ============================================================================


def aggregate_cross_zone_condensation(
    zone_condensation_states: dict,
) -> Optional[Insight]:
    """Aggregate condensation risk across zones.

    Triggers when 3+ zones have condensation risk, suggesting a
    whole-house ventilation issue.

    Args:
        zone_condensation_states: Dict mapping zone_name -> risk_level string

    Returns:
        Insight if whole-house condensation issue, None otherwise
    """
    if not zone_condensation_states:
        return None

    affected = [
        name for name, level in zone_condensation_states.items()
        if level not in ("unavailable", "unknown", "None", "Low", None)
    ]

    if len(affected) < 3:
        return None

    zones_str = ", ".join(affected[:5])
    rec = (
        f"Whole-house condensation risk: {len(affected)} zones affected "
        f"({zones_str}) - check ventilation system and consider "
        f"using a dehumidifier"
    )

    return Insight(
        priority=InsightPriority.HIGH,
        recommendation=rec,
        insight_type="cross_zone_condensation",
        zone_name=None,
    )


def calculate_cross_zone_efficiency_insight(
    zone_heating_rates: dict,
) -> Optional[Insight]:
    """Compare heating efficiency across zones.

    Triggers when one zone heats significantly slower than the average.

    Args:
        zone_heating_rates: Dict mapping zone_name -> heating_rate (°C/h)

    Returns:
        Insight if significant efficiency difference found, None otherwise
    """
    if not zone_heating_rates or len(zone_heating_rates) < 2:
        return None

    rates = list(zone_heating_rates.values())
    avg_rate = sum(rates) / len(rates)
    if avg_rate <= 0:
        return None

    # Find the slowest zone
    slowest_zone = min(zone_heating_rates, key=zone_heating_rates.get)
    slowest_rate = zone_heating_rates[slowest_zone]

    # Trigger if slowest is less than half the average
    if slowest_rate >= avg_rate * 0.5:
        return None

    rec = (
        f"{slowest_zone} heats at {slowest_rate:.2f}\u00b0C/h "
        f"(avg across zones: {avg_rate:.2f}\u00b0C/h) - "
        f"investigate insulation or radiator issues in this zone"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="cross_zone_efficiency",
        zone_name=None,
    )


def calculate_temperature_imbalance_insight(
    zone_temperatures: dict,
) -> Optional[Insight]:
    """Detect large temperature differences between active zones.

    Args:
        zone_temperatures: Dict mapping zone_name -> temperature (°C)
            Only include zones where power is ON.

    Returns:
        Insight if significant imbalance found, None otherwise
    """
    if not zone_temperatures or len(zone_temperatures) < 2:
        return None

    warmest_zone = max(zone_temperatures, key=zone_temperatures.get)
    coldest_zone = min(zone_temperatures, key=zone_temperatures.get)
    warmest_temp = zone_temperatures[warmest_zone]
    coldest_temp = zone_temperatures[coldest_zone]

    diff = warmest_temp - coldest_temp
    if diff < 4.0:
        return None

    rec = (
        f"Temperature imbalance: {warmest_zone} is {warmest_temp:.1f}\u00b0C "
        f"but {coldest_zone} is {coldest_temp:.1f}\u00b0C "
        f"({diff:.1f}\u00b0C difference) - check heat distribution"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="temp_imbalance",
        zone_name=None,
    )


def calculate_humidity_imbalance_insight(
    zone_humidities: dict,
) -> Optional[Insight]:
    """Detect when one zone has significantly higher humidity than others.

    Args:
        zone_humidities: Dict mapping zone_name -> humidity (%)

    Returns:
        Insight if significant humidity imbalance found, None otherwise
    """
    if not zone_humidities or len(zone_humidities) < 2:
        return None

    values = list(zone_humidities.values())
    avg_humidity = sum(values) / len(values)

    # Find the most humid zone
    most_humid_zone = max(zone_humidities, key=zone_humidities.get)
    most_humid_val = zone_humidities[most_humid_zone]

    excess = most_humid_val - avg_humidity
    if excess < 15:
        return None

    rec = (
        f"{most_humid_zone} humidity is {most_humid_val:.0f}% "
        f"({excess:.0f}% above average of {avg_humidity:.0f}%) "
        f"- check ventilation in this zone"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="humidity_imbalance",
        zone_name=None,
    )



# ============================================================================
# Category F (Environment Trends)
# ============================================================================


def calculate_humidity_trend_insight(
    current_humidity: Optional[float] = None,
    humidity_history: Optional[list] = None,
    zone_name: str = "",
) -> Optional[Insight]:
    """Detect rising humidity trend in a zone.

    Compares current humidity to the average of recent history to detect
    a significant upward trend.

    Args:
        current_humidity: Current humidity percentage
        humidity_history: List of recent humidity readings (floats)
        zone_name: Name of the zone

    Returns:
        Insight if humidity trending upward significantly, None otherwise
    """
    if current_humidity is None or not humidity_history:
        return None
    if len(humidity_history) < 6:
        return None

    avg_history = sum(humidity_history) / len(humidity_history)
    rise = current_humidity - avg_history
    if rise < 10:
        return None

    rec = (
        f"{zone_name}: Humidity rising - currently {current_humidity:.0f}% "
        f"(+{rise:.0f}% above recent average of {avg_history:.0f}%) "
        f"- ventilate to prevent mold risk"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="humidity_trend",
        zone_name=zone_name,
    )


# ============================================================================
# Category G (Device & System)
# ============================================================================


def calculate_device_limitation_insight(
    has_humidity_sensor: bool = True,
    has_temperature_sensor: bool = True,
    zone_name: str = "",
) -> Optional[Insight]:
    """Inform user when a zone device lacks expected sensors.

    Args:
        has_humidity_sensor: Whether the zone has humidity data
        has_temperature_sensor: Whether the zone has temperature data
        zone_name: Name of the zone

    Returns:
        Insight if device has missing sensors, None otherwise
    """
    if has_humidity_sensor and has_temperature_sensor:
        return None

    missing = []
    if not has_humidity_sensor:
        missing.append("humidity")
    if not has_temperature_sensor:
        missing.append("temperature")

    missing_str = " and ".join(missing)
    rec = (
        f"{zone_name}: Device has no {missing_str} sensor "
        f"- some insights (mold risk, comfort) may not be available"
    )

    return Insight(
        priority=InsightPriority.LOW,
        recommendation=rec,
        insight_type="device_limitation",
        zone_name=zone_name,
    )


def calculate_geofencing_device_offline_insight(
    devices: Optional[list] = None,
) -> Optional[Insight]:
    """Detect when a geofencing mobile device has location tracking disabled.

    Args:
        devices: List of dicts with keys: name, location_enabled (bool)

    Returns:
        Insight if any geofencing device is offline, None otherwise
    """
    if not devices:
        return None

    offline_devices = [
        d.get("name", "Unknown")
        for d in devices
        if not d.get("location_enabled", True)
    ]

    if not offline_devices:
        return None

    devices_str = ", ".join(offline_devices[:3])
    rec = (
        f"Geofencing device(s) with location disabled: {devices_str} "
        f"- home/away detection may be inaccurate"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="geofencing_offline",
        zone_name=None,
    )


def calculate_api_usage_spike_insight(
    current_hour_calls: Optional[int] = None,
    avg_calls_per_hour: Optional[float] = None,
) -> Optional[Insight]:
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
    if ratio < 2.0:
        return None

    rec = (
        f"API usage spike: {current_hour_calls} calls this hour "
        f"({ratio:.1f}x the average of {avg_calls_per_hour:.0f}/h) "
        f"- check for automation loops or integration conflicts"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="api_usage_spike",
        zone_name=None,
    )

