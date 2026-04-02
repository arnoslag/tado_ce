"""Environment insights — mold risk, comfort, condensation, humidity trend.

Provides recommendation functions for environment-related conditions
including mold risk, comfort levels, condensation, and humidity trends.
"""

from __future__ import annotations

from typing import Any

from .insights_models import (
    HUMIDITY_TREND_MIN_RISE,
    HUMIDITY_TREND_MIN_SAMPLES,
    MOLD_HUMIDITY_CRITICAL,
    MOLD_HUMIDITY_HIGH,
    MOLD_HUMIDITY_MEDIUM,
    MOLD_MARGIN_HIGH,
    MOLD_MARGIN_MEDIUM,
    Insight,
    InsightPriority,
)


def calculate_mold_risk_recommendation(  # noqa: C901, PLR0913, PLR0911, PLR0912
    risk_level: str,
    zone_name: str,
    humidity: float | None = None,
    surface_temp: float | None = None,
    dew_point: float | None = None,
    current_temp: float | None = None,
    target_temp: float | None = None,
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
        margin = surface_temp - dew_point

    # Level transition targets (margin thresholds)
    # Critical (<3) -> High needs margin >= 3
    # High (3-5) -> Medium needs margin >= 5
    # Medium (5-7) -> Low needs margin >= 7

    if risk_level == "Critical":
        # Target: move to High (margin >= 3)
        transition = "Critical\u2192High"
        actions = []
        if humidity and humidity > MOLD_HUMIDITY_CRITICAL:
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
                actions.append("check wall/window insulation \u2014 room warm but surfaces cold")
            else:
                delta = round(suggested - current_temp, 1)
                actions.append(f"increase heating by +{delta}\u00b0C (to {suggested:.0f}\u00b0C)")

        if actions:
            return f"{zone_name} [{transition}]: URGENT \u2014 {' and '.join(actions)}. Ventilate 10 min."
        return f"{zone_name} [{transition}]: URGENT \u2014 Ventilate 10 min and increase heating by +2\u00b0C"

    if risk_level == "High":
        # Target: move to Medium (margin >= 5)
        transition = "High\u2192Medium"
        if humidity and humidity > MOLD_HUMIDITY_HIGH:
            delta_h = round(humidity - 55)
            return (
                f"{zone_name} [{transition}]: Humidity {humidity:.0f}% "
                f"(reduce by {delta_h}% to 55%) \u2014 dehumidifier or ventilate 15 min"
            )
        if margin is not None and margin < MOLD_MARGIN_HIGH:
            needed = round(5 - margin, 1)
            # Use target_temp as base when available,
            # guard against suggesting temp <= current_temp
            base_temp = target_temp or current_temp
            if base_temp:
                suggested = base_temp + 1.5
                if current_temp and suggested <= current_temp:
                    # Room already warm — issue is insulation, not heating
                    return (
                        f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                        f"(need +{needed}\u00b0C margin) \u2014 improve insulation or ventilate 15 min"
                    )
                return (
                    f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                    f"(need +{needed}\u00b0C margin) \u2014 increase heating by +1.5\u00b0C (to {suggested:.0f}\u00b0C)"
                )
        return f"{zone_name} [{transition}]: Ventilate 15 min or increase heating by +1.5\u00b0C"

    if risk_level == "Medium":
        # Target: move to Low (margin >= 7)
        transition = "Medium\u2192Low"
        if humidity and humidity > MOLD_HUMIDITY_MEDIUM:
            delta_h = round(humidity - 55)
            return (
                f"{zone_name} [{transition}]: Humidity {humidity:.0f}% "
                f"(reduce by {delta_h}% to 55%) \u2014 ventilate 10 min after cooking/showering"
            )
        if margin is not None and margin < MOLD_MARGIN_MEDIUM:
            needed = round(7 - margin, 1)
            return (
                f"{zone_name} [{transition}]: Surface {margin:.1f}\u00b0C above dew point "
                f"(need +{needed}\u00b0C margin) \u2014 ensure adequate ventilation"
            )
        return f"{zone_name} [{transition}]: Moderate risk \u2014 ventilate daily 10 min"

    return ""


def calculate_comfort_recommendation(  # noqa: C901, PLR0913, PLR0911, PLR0912
    comfort_state: str,
    zone_name: str,
    current_temp: float | None = None,
    target_temp: float | None = None,
    humidity: float | None = None,
    hvac_mode: str | None = None,
    hvac_action: str | None = None,
    heat_index: float | None = None,
    heat_risk_level: str | None = None,
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
        heat_index: Calculated Heat Index in °C, or None.
        heat_risk_level: NOAA risk level string, or None.

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
                        f"target {target_temp:.0f}\u00b0C \u2014 turn on heating"
                    )
                # Differentiate based on hvac_action
                if hvac_action == "heating":
                    return (
                        f"{zone_name}: Heating in progress \u2014 "
                        f"{current_temp:.1f}\u00b0C, {diff:.1f}\u00b0C below target. "
                        f"Allow 15\u201330 min to reach {target_temp:.0f}\u00b0C"
                    )
                if hvac_action in ("idle", "off"):
                    suggested = min(target_temp + 1, 25)
                    return (
                        f"{zone_name}: {current_temp:.1f}\u00b0C, "
                        f"{diff:.1f}\u00b0C below target but heating idle \u2014 "
                        f"increase setpoint to {suggested:.0f}\u00b0C"
                    )
                # Unknown hvac_action - generic
                suggested = min(target_temp + 1, 25)
                return (
                    f"{zone_name}: {current_temp:.1f}\u00b0C, "
                    f"{diff:.1f}\u00b0C below target \u2014 "
                    f"increase setpoint to {suggested:.0f}\u00b0C if not warming up"
                )
            # Remove min() cap that could suggest
            # temp <= current_temp. Use current_temp + 2 directly.
            suggested = current_temp + 2
            return f"{zone_name}: {current_temp:.1f}\u00b0C feels cold \u2014 set heating to {suggested:.0f}\u00b0C"
        return f"{zone_name}: Room too cold \u2014 increase heating setpoint by 2\u00b0C"

    # Hot states
    if comfort_state in ("Too Hot", "Hot", "Warm", "Sweltering"):
        # Build heat index suffix
        hi_suffix = ""
        if heat_index is not None and heat_risk_level is not None and heat_risk_level != "None":
            hi_suffix = f" (feels like {heat_index:.1f}°C — {heat_risk_level})"

        if current_temp is not None:
            if target_temp is not None and current_temp > target_temp:
                over = round(current_temp - target_temp, 1)
                rec = (
                    f"{zone_name}: {current_temp:.1f}°C, "
                    f"{over:.1f}°C above target \u2014 open window or reduce heating"
                    f"{hi_suffix}"
                )
            else:
                suggested = max(current_temp - 2, 18)
                rec = (
                    f"{zone_name}: {current_temp:.1f}°C too warm \u2014 "
                    f"reduce setpoint to {suggested:.0f}°C or open window"
                    f"{hi_suffix}"
                )
        else:
            rec = f"{zone_name}: Room too hot \u2014 reduce heating setpoint by 2°C or open window{hi_suffix}"

        # Prepend urgency for Danger / Extreme Danger
        if heat_risk_level in ("Danger", "Extreme Danger"):
            rec = f"⚠️ {zone_name}: Heat risk {heat_risk_level} — {rec[len(zone_name) + 2:]}"

        return rec

    if comfort_state == "Too Humid":
        if humidity is not None:
            return f"{zone_name}: Humidity {humidity:.0f}% too high \u2014 run dehumidifier or ventilate to reach 55%"
        return f"{zone_name}: High humidity \u2014 run dehumidifier or open window for 15 minutes"

    if comfort_state == "Too Dry":
        if humidity is not None:
            return f"{zone_name}: Humidity {humidity:.0f}% too low \u2014 use humidifier to reach 45%"
        return f"{zone_name}: Low humidity \u2014 use humidifier or place water bowl near radiator"

    return ""


def calculate_condensation_recommendation(  # noqa: PLR0911
    risk_level: str,
    zone_name: str,
    margin: float | None = None,
    ac_setpoint: float | None = None,
    current_temp: float | None = None,  # noqa: ARG001 — reserved for future use
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
                f"{zone_name}: URGENT condensation risk \u2014 increase AC setpoint "
                f"from {ac_setpoint:.0f}°C to {suggested:.0f}°C immediately"
            )
        return f"{zone_name}: URGENT condensation risk \u2014 increase AC setpoint by 2°C and improve ventilation"

    if risk_level == "High":
        if ac_setpoint is not None and margin is not None:
            suggested = ac_setpoint + 1
            return f"{zone_name}: Only {margin:.1f}°C above dew point \u2014 increase AC setpoint to {suggested:.0f}°C"
        return f"{zone_name}: High condensation risk \u2014 increase AC setpoint by 1°C"

    if risk_level == "Medium":
        if margin is not None:
            return (
                f"{zone_name}: {margin:.1f}°C above dew point "
                f"\u2014 monitor conditions, consider raising AC setpoint"
            )
        return f"{zone_name}: Moderate condensation risk \u2014 ensure adequate ventilation"

    return ""


def calculate_heating_condensation_recommendation(  # noqa: PLR0913
    risk_level: str,
    zone_name: str,
    margin: float | None = None,
    humidity: float | None = None,  # noqa: ARG001 — reserved for future use
    surface_temp: float | None = None,
    dew_point: float | None = None,
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
                f"Surface temp {surface_temp:.1f}°C is {abs(margin):.1f}°C below dew point {dew_point:.1f}°C",
            )
        parts.append("Open window briefly, use extractor fan, wipe surfaces")
        return ". ".join(parts)

    if risk_level == "High":
        parts = [f"{zone_name}: Windows likely fogging"]
        if margin is not None and dew_point is not None:
            parts.append(
                f"Surface temp only {margin:.1f}°C above dew point {dew_point:.1f}°C",
            )
        parts.append("Ventilate or increase heating")
        return ". ".join(parts)

    if risk_level == "Medium":
        parts = [f"{zone_name}: Monitor — condensation possible"]
        if margin is not None and dew_point is not None:
            parts.append(
                f"Surface temp {margin:.1f}°C above dew point {dew_point:.1f}°C",
            )
        parts.append("Ensure adequate ventilation")
        return ". ".join(parts)

    return ""


def calculate_humidity_trend_insight(
    current_humidity: float | None = None,
    humidity_history: list[Any] | None = None,
    zone_name: str = "",
) -> Insight | None:
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
    if len(humidity_history) < HUMIDITY_TREND_MIN_SAMPLES:
        return None

    avg_history = sum(humidity_history) / len(humidity_history)
    rise = current_humidity - avg_history
    if rise < HUMIDITY_TREND_MIN_RISE:
        return None

    rec = (
        f"{zone_name}: Humidity rising \u2014 currently {current_humidity:.0f}% "
        f"(+{rise:.0f}% above recent average of {avg_history:.0f}%) "
        f"\u2014 ventilate to prevent mold risk"
    )

    return Insight(
        priority=InsightPriority.MEDIUM,
        recommendation=rec,
        insight_type="humidity_trend",
        zone_name=zone_name,
    )
