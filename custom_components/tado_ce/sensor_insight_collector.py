"""Tado CE Insight Collector — standalone functions for insight collection.

Functions accept hass, coordinator, and mutable state dicts as parameters
instead of accessing self.* attributes.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .insights import (
    Insight,
    aggregate_cross_zone_condensation,
    aggregate_cross_zone_mold_risk,
    aggregate_cross_zone_window_predicted,
    calculate_api_quota_planning_insight,
    calculate_api_usage_spike_insight,
    calculate_away_heating_active_insight,
    calculate_battery_recommendation,
    calculate_boiler_flow_anomaly_insight,
    calculate_calls_per_hour,
    calculate_comfort_recommendation,
    calculate_connection_recommendation,
    calculate_cross_zone_efficiency_insight,
    calculate_device_limitation_insight,
    calculate_early_start_disabled_insight,
    calculate_frequent_override_insight,
    calculate_frost_risk_insight,
    calculate_geofencing_device_offline_insight,
    calculate_heating_anomaly_insight,
    calculate_heating_off_cold_room_insight,
    calculate_heating_season_advisory_insight,
    calculate_home_all_off_insight,
    calculate_humidity_imbalance_insight,
    calculate_humidity_trend_insight,
    calculate_mold_risk_recommendation,
    calculate_overlay_duration_insight,
    calculate_poor_thermal_efficiency_insight,
    calculate_preheat_timing_insight,
    calculate_schedule_gap_insight,
    calculate_solar_ac_load_insight,
    calculate_solar_gain_insight,
    calculate_temperature_imbalance_insight,
    calculate_weather_impact_insight,
    classify_comfort_level,
    classify_mold_risk_level,
    get_insight_priority,
)

_LOGGER = logging.getLogger(__name__)


def collect_single_zone_insights(
    hass,
    coordinator,
    zone_id: str,
    zone_name: str,
    zone_data: dict,
    zones_info: list | None,
    anomaly_start_times: dict[str, datetime],
    humidity_histories: dict[str, list] | None = None,
    schedules: dict | None = None,
) -> list:
    """Collect all insights for a single zone.

    Shared by both TadoHomeInsightsSensor (via collect_zone_insights)
    and TadoZoneInsightsSensor (direct call). This eliminates the
    "改啲唔改啲" risk of duplicated insight logic.

    Args:
        hass: Home Assistant instance.
        coordinator: TadoDataUpdateCoordinator instance.
        zone_id: Zone ID string.
        zone_name: Human-readable zone name.
        zone_data: Zone state dict from zoneStates.
        zones_info: List of zone info dicts (for battery/connection/device).
        anomaly_start_times: Mutable dict tracking per-zone anomaly start.
        humidity_histories: Mutable dict for humidity trend (Home sensor only).
        schedules: Pre-loaded schedules dict (None = skip schedule gap).

    Returns:
        List of Insight objects for this zone.
    """
    insights: list = []

    sensor_data = zone_data.get("sensorDataPoints") or {}
    humidity = (sensor_data.get("humidity") or {}).get("percentage")
    inside_temp = (sensor_data.get("insideTemperature") or {}).get("celsius")

    # --- Mold risk ---
    if humidity is not None and inside_temp is not None:
        risk = classify_mold_risk_level(inside_temp, humidity)
        if risk in ("Critical", "High", "Medium"):
            rec = calculate_mold_risk_recommendation(
                risk_level=risk, zone_name=zone_name,
                humidity=humidity, current_temp=inside_temp,
            )
            insights.append(Insight(
                priority=get_insight_priority("mold_risk", risk.lower()),
                recommendation=rec, insight_type="mold_risk",
                zone_name=zone_name,
            ))

    # --- Comfort (skip when heating OFF) ---
    setting = zone_data.get("setting") or {}
    power = setting.get("power", "OFF")
    if inside_temp is not None and power == "ON":
        comfort_state = classify_comfort_level(inside_temp)
        if comfort_state in ("Cold", "Cool", "Freezing"):
            rec = calculate_comfort_recommendation(
                comfort_state=comfort_state, zone_name=zone_name,
                current_temp=inside_temp,
            )
            insights.append(Insight(
                priority=get_insight_priority("comfort", "too_cold"),
                recommendation=rec, insight_type="comfort",
                zone_name=zone_name,
            ))
        elif comfort_state in ("Hot", "Sweltering"):
            rec = calculate_comfort_recommendation(
                comfort_state=comfort_state, zone_name=zone_name,
                current_temp=inside_temp,
            )
            insights.append(Insight(
                priority=get_insight_priority("comfort", "too_hot"),
                recommendation=rec, insight_type="comfort",
                zone_name=zone_name,
            ))

    # --- HA entity-based insights ---
    if hass:
        slug = zone_name.lower().replace(" ", "_")
        _collect_ha_entity_insights(
            hass, slug, zone_name, zone_data, inside_temp,
            anomaly_start_times, insights,
        )

    # --- Overlay duration ---
    overlay_type = zone_data.get("overlayType")
    next_schedule_change = zone_data.get("nextScheduleChange")
    insight = calculate_overlay_duration_insight(
        overlay_type=overlay_type,
        next_schedule_change=next_schedule_change,
        zone_name=zone_name,
    )
    if insight:
        insights.append(insight)

    # --- Frequent override ---
    insight = calculate_frequent_override_insight(
        overlay_type=overlay_type, zone_name=zone_name,
    )
    if insight:
        insights.append(insight)

    # --- Heating off + cold room ---
    insight = calculate_heating_off_cold_room_insight(
        power_state=setting.get("power"),
        current_temp=inside_temp,
        target_temp=(setting.get("temperature") or {}).get("celsius"),
        zone_name=zone_name,
    )
    if insight:
        insights.append(insight)

    # --- Early start disabled ---
    if hass:
        slug = zone_name.lower().replace(" ", "_")
        insight = _check_early_start(hass, slug, zone_name)
        if insight:
            insights.append(insight)

    # --- Poor thermal efficiency ---
    if hass:
        slug = zone_name.lower().replace(" ", "_")
        insight = _check_thermal_efficiency(hass, slug, zone_name)
        if insight:
            insights.append(insight)

    # --- Schedule gap (Home sensor passes schedules; Zone sensor skips) ---
    if schedules and inside_temp is not None:
        insight = _check_schedule_gap(
            schedules, zone_id, zone_data, inside_temp, zone_name,
        )
        if insight:
            insights.append(insight)

    # --- Boiler flow anomaly ---
    activity = zone_data.get("activityDataPoints") or {}
    flow_data = activity.get("boilerFlowTemperature") or {}
    flow_temp = flow_data.get("celsius")
    if flow_temp is not None:
        hp_pct = (activity.get("heatingPower") or {}).get("percentage")
        insight = calculate_boiler_flow_anomaly_insight(
            flow_temp=flow_temp, heating_power_pct=hp_pct,
            zone_name=zone_name,
        )
        if insight:
            insights.append(insight)

    # --- Device limitation ---
    if zones_info:
        zone_info = next(
            (z for z in zones_info if str(z.get("id")) == zone_id), None,
        )
        if zone_info:
            insight = calculate_device_limitation_insight(
                has_humidity_sensor=humidity is not None,
                has_temperature_sensor=inside_temp is not None,
                zone_name=zone_name,
            )
            if insight:
                insights.append(insight)

    # --- Humidity trend (Home sensor only — needs history tracking) ---
    if humidity_histories is not None and humidity is not None:
        if zone_name not in humidity_histories:
            humidity_histories[zone_name] = []
        humidity_histories[zone_name].append(humidity)
        if len(humidity_histories[zone_name]) > 48:
            humidity_histories[zone_name] = humidity_histories[zone_name][-48:]
        insight = calculate_humidity_trend_insight(
            current_humidity=humidity,
            humidity_history=humidity_histories[zone_name],
            zone_name=zone_name,
        )
        if insight:
            insights.append(insight)

    # --- Battery and connection ---
    if zones_info:
        _collect_single_zone_device_insights(zone_id, zone_name, zones_info, insights)

    return insights


def collect_zone_insights(
    hass,
    coordinator,
    anomaly_start_times: dict[str, datetime],
    humidity_histories: dict[str, list],
) -> dict[str, list]:
    """Collect insights from all zones by reading zone data files.

    Args:
        hass: Home Assistant instance.
        coordinator: TadoDataUpdateCoordinator instance.
        anomaly_start_times: Mutable dict tracking per-zone anomaly start times.
        humidity_histories: Mutable dict tracking per-zone humidity history.

    Returns:
        Dict mapping zone names to lists of Insight objects.
    """
    zone_insights: dict[str, list] = {}

    try:
        coord_data = coordinator.data or {}
        zones_data = coord_data.get("zones")
        zones_info = coord_data.get("zones_info")
        if not zones_data:
            return zone_insights

        zone_states = zones_data.get("zoneStates") or {}
        schedules = coord_data.get("schedules")

        zone_name_map: dict[str, str] = {}
        if zones_info:
            for z in zones_info:
                zone_name_map[str(z.get("id"))] = z.get("name", f"Zone {z.get('id')}")

        for zone_id, zone_data in zone_states.items():
            zone_name = zone_name_map.get(zone_id, f"Zone {zone_id}")
            insights = collect_single_zone_insights(
                hass=hass,
                coordinator=coordinator,
                zone_id=zone_id,
                zone_name=zone_name,
                zone_data=zone_data,
                zones_info=zones_info,
                anomaly_start_times=anomaly_start_times,
                humidity_histories=humidity_histories,
                schedules=schedules,
            )
            if insights:
                zone_insights[zone_name] = insights

    except Exception as e:
        _LOGGER.debug("Failed to collect zone insights: %s", e)

    return zone_insights


def _collect_ha_entity_insights(
    hass,
    slug: str,
    zone_name: str,
    zone_data: dict,
    inside_temp: float | None,
    anomaly_start_times: dict[str, datetime],
    insights: list,
) -> None:
    """Collect insights that depend on HA entity states.

    Handles condensation, window predicted, preheat timing, heating anomaly.
    """
    # Condensation risk
    cond_state = hass.states.get(f"sensor.{slug}_condensation_risk")
    if cond_state and cond_state.state not in ("unavailable", "unknown", "None", "Low"):
        cond_rec = (cond_state.attributes or {}).get("recommendation", "")
        if not cond_rec:
            cond_rec = f"{zone_name}: Condensation risk detected"
        insights.append(Insight(
            priority=get_insight_priority("condensation", cond_state.state.lower()),
            recommendation=cond_rec, insight_type="condensation",
            zone_name=zone_name,
        ))

    # Window predicted
    wp_state = hass.states.get(f"binary_sensor.{slug}_window_predicted")
    if wp_state and wp_state.state == "on":
        wp_rec = (wp_state.attributes or {}).get("recommendation", "")
        if not wp_rec:
            wp_rec = f"{zone_name}: Possible open window detected"
        insights.append(Insight(
            priority=get_insight_priority("window_predicted", "high"),
            recommendation=wp_rec, insight_type="window_predicted",
            zone_name=zone_name,
        ))

    # Preheat timing
    ph_state = hass.states.get(f"sensor.{slug}_preheat_time")
    sc_state = hass.states.get(f"sensor.{slug}_next_schedule_time")
    ph_min = _safe_float(ph_state)
    sc_val = sc_state.state if sc_state and sc_state.state not in ("unavailable", "unknown") else None
    insight = calculate_preheat_timing_insight(
        preheat_time_minutes=ph_min, next_schedule_time=sc_val,
        zone_name=zone_name,
    )
    if insight:
        insights.append(insight)

    # Heating anomaly
    pw_state = hass.states.get(f"sensor.{slug}_heating_power")
    if pw_state and pw_state.state not in ("unavailable", "unknown"):
        try:
            power_pct = float(pw_state.state)
            setting = zone_data.get("setting") or {}
            target = (setting.get("temperature") or {}).get("celsius")
            if inside_temp is not None and target is not None:
                temp_delta = abs(inside_temp - target)
                if power_pct >= 80 and temp_delta < 0.5:
                    if zone_name not in anomaly_start_times:
                        anomaly_start_times[zone_name] = datetime.now()
                    elapsed = (datetime.now() - anomaly_start_times[zone_name]).total_seconds() / 60
                    ha_insight = calculate_heating_anomaly_insight(
                        heating_power_pct=power_pct, temp_delta=temp_delta,
                        duration_minutes=int(elapsed), zone_name=zone_name,
                    )
                    if ha_insight:
                        insights.append(ha_insight)
                else:
                    anomaly_start_times.pop(zone_name, None)
        except (ValueError, TypeError):
            pass


def _safe_float(state) -> float | None:
    """Extract float from HA state, returning None if unavailable."""
    if state and state.state not in ("unavailable", "unknown"):
        try:
            return float(state.state)
        except (ValueError, TypeError):
            pass
    return None


def _check_early_start(hass, slug: str, zone_name: str):
    """Check early start disabled + long preheat insight."""
    es_state = hass.states.get(f"switch.{slug}_early_start")
    ph_state = hass.states.get(f"sensor.{slug}_preheat_time")
    early_start_on = True
    if es_state and es_state.state == "off":
        early_start_on = False
    return calculate_early_start_disabled_insight(
        early_start_enabled=early_start_on,
        preheat_time_minutes=_safe_float(ph_state),
        zone_name=zone_name,
    )


def _check_thermal_efficiency(hass, slug: str, zone_name: str):
    """Check poor thermal efficiency insight."""
    ti_val = _safe_float(hass.states.get(f"sensor.{slug}_thermal_inertia"))
    hr_val = _safe_float(hass.states.get(f"sensor.{slug}_avg_heating_rate"))
    conf_val = _safe_float(hass.states.get(f"sensor.{slug}_analysis_confidence"))
    return calculate_poor_thermal_efficiency_insight(
        thermal_inertia=ti_val, heating_rate=hr_val,
        confidence_score=conf_val, zone_name=zone_name,
    )


def _check_schedule_gap(
    schedules: dict,
    zone_id: str,
    zone_data: dict,
    inside_temp: float,
    zone_name: str,
):
    """Check schedule gap insight for a zone."""
    zone_schedule = schedules.get(zone_id)
    if not zone_schedule:
        return None

    raw_blocks = zone_schedule.get("blocks") or zone_schedule.get("schedule", [])
    if isinstance(raw_blocks, dict):
        blocks = [b for day_blocks in raw_blocks.values() for b in day_blocks]
    else:
        blocks = raw_blocks

    setting = zone_data.get("setting") or {}
    next_target = (setting.get("temperature") or {}).get("celsius")

    longest_off = None
    if blocks:
        off_durations = []
        for block in blocks:
            block_setting = block.get("setting") or {}
            if block_setting.get("power") == "OFF":
                start_str = block.get("start", "")
                end_str = block.get("end", "")
                if start_str and end_str:
                    try:
                        sh, sm = int(start_str.split(":")[0]), int(start_str.split(":")[1])
                        eh, em = int(end_str.split(":")[0]), int(end_str.split(":")[1])
                        dur = (eh * 60 + em) - (sh * 60 + sm)
                        if dur < 0:
                            dur += 24 * 60
                        off_durations.append(dur / 60.0)
                    except (ValueError, IndexError):
                        pass
        if off_durations:
            longest_off = max(off_durations)

    return calculate_schedule_gap_insight(
        schedule_blocks=blocks if blocks else None,
        current_temp=inside_temp,
        next_target_temp=next_target,
        longest_off_hours=longest_off,
        zone_name=zone_name,
    )


def _collect_single_zone_device_insights(
    zone_id: str,
    zone_name: str,
    zones_info: list,
    insights: list,
) -> None:
    """Collect battery and connection insights for a single zone."""
    zone_info = next(
        (z for z in zones_info if str(z.get("id")) == zone_id), None,
    )
    if not zone_info:
        return

    for device in zone_info.get("devices", []):
        battery = device.get("batteryState")
        if battery and battery.upper() in ("LOW", "CRITICAL"):
            device_type = device.get("deviceType", "unknown")
            rec = calculate_battery_recommendation(
                battery_state=battery, zone_name=zone_name,
                device_type=device_type,
            )
            severity = "critical" if battery.upper() == "CRITICAL" else "low"
            insights.append(Insight(
                priority=get_insight_priority("battery", severity),
                recommendation=rec, insight_type="battery",
                zone_name=zone_name,
            ))

        conn = device.get("connectionState") or {}
        conn_value = conn.get("value")
        if conn_value is not None and not conn_value:
            rec = calculate_connection_recommendation(
                connection_state="Offline", zone_name=zone_name,
            )
            insights.append(Insight(
                priority=get_insight_priority("connection", "offline"),
                recommendation=rec, insight_type="connection",
                zone_name=zone_name,
            ))



def get_cross_zone_insights(
    hass,
    coordinator,
    zone_insights: dict[str, list],
) -> list:
    """Get cross-zone aggregation insights.

    Checks for whole-house mold risk, multiple open windows,
    condensation aggregation, efficiency comparison, temperature
    and humidity imbalance.

    Args:
        hass: Home Assistant instance.
        coordinator: TadoDataUpdateCoordinator instance.
        zone_insights: Already collected per-zone insights.

    Returns:
        List of cross-zone Insight objects.
    """
    cross_insights: list = []

    try:
        coord_data = coordinator.data or {}
        zones_data = coord_data.get("zones")
        zones_info = coord_data.get("zones_info")

        zone_name_map: dict[str, str] = {}
        if zones_info:
            for z in zones_info:
                zone_name_map[str(z.get("id"))] = z.get("name", f"Zone {z.get('id')}")

        # Cross-zone mold risk
        if zones_data:
            zone_states = zones_data.get("zoneStates") or {}
            zone_mold_risks: dict[str, str] = {}
            for zone_id, zone_data in zone_states.items():
                zone_name = zone_name_map.get(zone_id, f"Zone {zone_id}")
                sensor_data = zone_data.get("sensorDataPoints") or {}
                humidity = (sensor_data.get("humidity") or {}).get("percentage")
                inside_temp = (sensor_data.get("insideTemperature") or {}).get("celsius")
                if humidity is not None and inside_temp is not None:
                    zone_mold_risks[zone_name] = classify_mold_risk_level(inside_temp, humidity)

            mold_insight = aggregate_cross_zone_mold_risk(zone_mold_risks)
            if mold_insight:
                cross_insights.append(mold_insight)

        # Cross-zone window predicted
        if hass:
            zone_window_states: dict[str, bool] = {}
            for zone_name in zone_insights:
                slug = zone_name.lower().replace(" ", "_")
                wp_state = hass.states.get(f"binary_sensor.{slug}_window_predicted")
                if wp_state:
                    zone_window_states[zone_name] = wp_state.state == "on"
            window_insight = aggregate_cross_zone_window_predicted(zone_window_states)
            if window_insight:
                cross_insights.append(window_insight)

        # Cross-zone condensation
        if hass and zones_info:
            zone_cond_states: dict[str, str] = {}
            for z in zones_info:
                z_name = z.get("name", f"Zone {z.get('id')}")
                slug = z_name.lower().replace(" ", "_")
                cond_state = hass.states.get(f"sensor.{slug}_condensation_risk")
                if cond_state and cond_state.state not in ("unavailable", "unknown"):
                    zone_cond_states[z_name] = cond_state.state
            cond_insight = aggregate_cross_zone_condensation(zone_cond_states)
            if cond_insight:
                cross_insights.append(cond_insight)

        # Cross-zone efficiency comparison
        if hass and zones_info:
            zone_heating_rates: dict[str, float] = {}
            for z in zones_info:
                z_name = z.get("name", f"Zone {z.get('id')}")
                slug = z_name.lower().replace(" ", "_")
                hr_val = _safe_float(hass.states.get(f"sensor.{slug}_avg_heating_rate"))
                if hr_val is not None:
                    zone_heating_rates[z_name] = hr_val
            eff_insight = calculate_cross_zone_efficiency_insight(zone_heating_rates)
            if eff_insight:
                cross_insights.append(eff_insight)

        # Temperature imbalance
        if zones_data:
            zone_states = zones_data.get("zoneStates") or {}
            zone_temps: dict[str, float] = {}
            for zid, zd in zone_states.items():
                z_name = zone_name_map.get(zid, f"Zone {zid}")
                s = zd.get("setting") or {}
                if s.get("power") == "ON":
                    sd = zd.get("sensorDataPoints") or {}
                    t = (sd.get("insideTemperature") or {}).get("celsius")
                    if t is not None:
                        zone_temps[z_name] = t
            temp_insight = calculate_temperature_imbalance_insight(zone_temps)
            if temp_insight:
                cross_insights.append(temp_insight)

        # Humidity imbalance
        if zones_data:
            zone_hums: dict[str, float] = {}
            for zid, zd in zone_states.items():
                z_name = zone_name_map.get(zid, f"Zone {zid}")
                sd = zd.get("sensorDataPoints") or {}
                h = (sd.get("humidity") or {}).get("percentage")
                if h is not None:
                    zone_hums[z_name] = h
            hum_insight = calculate_humidity_imbalance_insight(zone_hums)
            if hum_insight:
                cross_insights.append(hum_insight)

    except Exception as e:
        _LOGGER.debug("Failed to collect cross-zone insights: %s", e)

    return cross_insights



def get_hub_insights(
    hass,
    coordinator,
) -> list:
    """Get hub-level insights (API quota, weather, presence).

    Args:
        hass: Home Assistant instance.
        coordinator: TadoDataUpdateCoordinator instance.

    Returns:
        List of hub-level Insight objects.
    """
    hub_insights: list = []

    try:
        coord_data = coordinator.data or {}

        # --- API quota planning ---
        ratelimit = coord_data.get("ratelimit")
        if ratelimit:
            remaining = ratelimit.get("remaining")
            total = ratelimit.get("limit")
            reset_seconds = ratelimit.get("reset_seconds")
            hours_until_reset = None
            if reset_seconds is not None and reset_seconds > 0:
                hours_until_reset = reset_seconds / 3600

            history_raw = coord_data.get("api_call_history")
            if history_raw and isinstance(history_raw, dict):
                history = [call for calls in history_raw.values() for call in calls]
            else:
                history = history_raw or []
            calls_per_hour = calculate_calls_per_hour(history) if history else None

            if remaining is not None and calls_per_hour is not None:
                insight = calculate_api_quota_planning_insight(
                    remaining_calls=remaining, total_calls=total,
                    calls_per_hour=calls_per_hour,
                    hours_until_reset=hours_until_reset,
                )
                if insight:
                    hub_insights.append(insight)

        # --- Weather impact ---
        weather = coord_data.get("weather")
        if weather:
            outdoor_temp = (weather.get("outsideTemperature") or {}).get("celsius")
            if outdoor_temp is not None:
                # History is now owned and persisted by the coordinator
                outdoor_temp_history = coordinator.outdoor_temp_history

                avg_7d = None
                if len(outdoor_temp_history) >= 48:
                    avg_7d = sum(outdoor_temp_history) / len(outdoor_temp_history)
                insight = calculate_weather_impact_insight(
                    current_outdoor_temp=outdoor_temp, avg_outdoor_temp_7d=avg_7d,
                )
                if insight:
                    hub_insights.append(insight)

                # Frost risk
                frost_insight = calculate_frost_risk_insight(outdoor_temp=outdoor_temp)
                if frost_insight:
                    hub_insights.append(frost_insight)

                # Heating season advisory
                if len(outdoor_temp_history) >= 96:
                    mid = len(outdoor_temp_history) // 2
                    prev_avg = sum(outdoor_temp_history[:mid]) / mid
                    curr_avg = sum(outdoor_temp_history[mid:]) / (len(outdoor_temp_history) - mid)
                    season_insight = calculate_heating_season_advisory_insight(
                        current_avg_7d=curr_avg, previous_avg_7d=prev_avg,
                    )
                    if season_insight:
                        hub_insights.append(season_insight)

                # Solar gain / Solar AC load
                _collect_solar_insights(
                    hass, coordinator, weather, outdoor_temp, hub_insights,
                )

        # --- Away + heating active / Home + all off ---
        _collect_presence_insights(hass, coordinator, hub_insights)

        # --- Geofencing device offline ---
        mobile_devices = coord_data.get("mobile_devices")
        if mobile_devices:
            device_list = [
                {
                    "name": md.get("name", "Unknown"),
                    "location_enabled": (md.get("settings") or {}).get(
                        "geoTrackingEnabled", True,
                    ),
                }
                for md in mobile_devices
            ]
            geo_insight = calculate_geofencing_device_offline_insight(devices=device_list)
            if geo_insight:
                hub_insights.append(geo_insight)

        # --- API usage spike ---
        _collect_api_spike_insight(coord_data, hub_insights)

    except Exception as e:
        _LOGGER.debug("Failed to collect hub insights: %s", e)

    return hub_insights



def _collect_solar_insights(
    hass, coordinator, weather: dict, outdoor_temp: float, hub_insights: list,
) -> None:
    """Collect solar gain and solar AC load insights."""
    solar_pct = (weather.get("solarIntensity") or {}).get("percentage")
    if solar_pct is None:
        return

    coord_data = coordinator.data or {}
    zones_data = coord_data.get("zones")
    zones_info = coord_data.get("zones_info")
    if not zones_data or not zones_info:
        return

    zone_states = zones_data.get("zoneStates") or {}
    zone_name_map: dict[str, str] = {}
    for z in zones_info:
        zone_name_map[str(z.get("id"))] = z.get("name", f"Zone {z.get('id')}")

    heating_active = []
    ac_active = []
    for zid, zd in zone_states.items():
        s = zd.get("setting") or {}
        if s.get("power") != "ON":
            continue
        z_name = zone_name_map.get(zid, f"Zone {zid}")
        hp = (zd.get("activityDataPoints") or {}).get("heatingPower") or {}
        pct = hp.get("percentage", 0)
        if s.get("type") == "HEATING" and pct > 0:
            heating_active.append({"zone_name": z_name, "power_pct": pct})
        elif s.get("type") == "AIR_CONDITIONING":
            ac_active.append({"zone_name": z_name})

    sg_insight = calculate_solar_gain_insight(
        solar_intensity_pct=solar_pct,
        heating_zones_active=heating_active if heating_active else None,
    )
    if sg_insight:
        hub_insights.append(sg_insight)

    sac_insight = calculate_solar_ac_load_insight(
        solar_intensity_pct=solar_pct,
        ac_zones_active=ac_active if ac_active else None,
    )
    if sac_insight:
        hub_insights.append(sac_insight)


def _collect_presence_insights(hass, coordinator, hub_insights: list) -> None:
    """Collect away+heating and home+all-off insights."""
    coord_data = coordinator.data or {}
    home_state_data = coord_data.get("home_state")
    if not home_state_data:
        return

    presence = home_state_data.get("presence")
    zones_data = coord_data.get("zones")
    zones_info = coord_data.get("zones_info")
    if not zones_data or not zones_info:
        return

    zone_states = zones_data.get("zoneStates") or {}
    zone_name_map: dict[str, str] = {}
    for z in zones_info:
        zone_name_map[str(z.get("id"))] = z.get("name", f"Zone {z.get('id')}")

    active_zones = []
    all_off = True
    coldest_name = None
    coldest_temp = None
    coldest_target = None

    for zid, zd in zone_states.items():
        s = zd.get("setting") or {}
        if s.get("type") == "HOT_WATER":
            continue
        if s.get("power") == "ON":
            all_off = False
            hp = (zd.get("activityDataPoints") or {}).get("heatingPower") or {}
            pct = hp.get("percentage", 0)
            z_name = zone_name_map.get(zid, f"Zone {zid}")
            if pct > 0:
                active_zones.append({
                    "zone_name": z_name, "power_pct": pct,
                    "zone_type": s.get("type", "HEATING"),
                })
        sd = zd.get("sensorDataPoints") or {}
        t = (sd.get("insideTemperature") or {}).get("celsius")
        tgt = (s.get("temperature") or {}).get("celsius")
        if t is not None:
            z_name = zone_name_map.get(zid, f"Zone {zid}")
            if coldest_temp is None or t < coldest_temp:
                coldest_temp = t
                coldest_name = z_name
                coldest_target = tgt

    away_insight = calculate_away_heating_active_insight(
        presence=presence,
        active_zones=active_zones if active_zones else None,
    )
    if away_insight:
        hub_insights.append(away_insight)

    home_off_insight = calculate_home_all_off_insight(
        presence=presence, all_zones_off=all_off,
        coldest_zone_name=coldest_name, coldest_zone_temp=coldest_temp,
        coldest_zone_target=coldest_target,
    )
    if home_off_insight:
        hub_insights.append(home_off_insight)


def _collect_api_spike_insight(coord_data, hub_insights: list) -> None:
    """Collect API usage spike insight."""
    history_raw = coord_data.get("api_call_history")
    if not history_raw or not isinstance(history_raw, dict):
        return

    all_calls = [call for calls in history_raw.values() for call in calls]
    cph = calculate_calls_per_hour(all_calls) if all_calls else None

    now = datetime.now()
    today_key = now.strftime("%Y-%m-%d")
    today_calls = history_raw.get(today_key, [])
    current_hour_calls = 0
    for call in today_calls:
        ts = call.get("timestamp") or call.get("time", "")
        if ts:
            try:
                call_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if call_time.hour == now.hour:
                    current_hour_calls += 1
            except (ValueError, TypeError):
                pass

    if cph is not None and current_hour_calls > 0:
        spike_insight = calculate_api_usage_spike_insight(
            current_hour_calls=current_hour_calls, avg_calls_per_hour=cph,
        )
        if spike_insight:
            hub_insights.append(spike_insight)
